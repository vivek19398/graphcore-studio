"""Immutable local typed CSV artifacts and deterministic decimal summaries."""
import csv
import hashlib
import io
import json
import re
import threading
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

class LocalTables:
    MAX_BYTES = 2 * 1024 * 1024
    MAX_ROWS = 20000
    MAX_COLUMNS = 100

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def _path(self, ident):
        if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{64}', ident):
            raise ValueError('Invalid table artifact ID')
        return self.root / (ident + '.json')

    def read(self, ident):
        raw = self._path(ident).read_bytes()
        if hashlib.sha256(raw).hexdigest() != ident:
            raise ValueError('Table artifact integrity check failed')
        return json.loads(raw)

    def metadata(self, ident, table):
        return {'type': 'table_ref', 'id': ident, 'name': table['name'],
                'row_count': len(table['rows']), 'columns': table['columns'],
                'source_sha256': table['source_sha256'],
                **({'provenance': table['provenance']} if 'provenance' in table else {})}

    def list(self):
        with self.lock:
            return [self.metadata(p.stem, self.read(p.stem))
                    for p in sorted(self.root.glob('*.json'))]

    def _parse(self, name, text, types=None):
        if not isinstance(name, str) or not name.lower().endswith('.csv') or '/' in name or '\\' in name or len(name) > 200:
            raise ValueError('Choose a CSV filename without directory paths')
        if not isinstance(text, str) or '\x00' in text or len(text.encode('utf-8')) > self.MAX_BYTES:
            raise ValueError('CSV must be UTF-8 text up to 2 MiB without NUL characters')
        types = {} if types is None else types
        if not isinstance(types, dict): raise ValueError('Column types must be an object')
        try:
            records = csv.reader(io.StringIO(text.lstrip('\ufeff')), strict=True)
            headers = next(records)
            if not headers or len(headers) > self.MAX_COLUMNS or any(not h.strip() for h in headers) or len(set(headers)) != len(headers):
                raise ValueError('CSV needs 1–100 unique, nonempty column headers')
            if set(types) - set(headers) or any(t not in ('string', 'integer', 'decimal', 'boolean') for t in types.values()):
                raise ValueError('Types must reference existing columns: string, integer, decimal, boolean')
            rows = []
            for line, values in enumerate(records, 2):
                if len(rows) >= self.MAX_ROWS: raise ValueError('CSV exceeds 20000 rows')
                if len(values) != len(headers): raise ValueError('CSV row %d has an incorrect column count' % line)
                row = {}
                for key, value in zip(headers, values):
                    kind = types.get(key, 'string')
                    try:
                        if value == '': value = None
                        elif kind == 'integer':
                            if len(value.lstrip('+-')) > 100 or not re.fullmatch(r'[+-]?\d+', value): raise ValueError()
                            value = int(value)
                        elif kind == 'decimal':
                            number = Decimal(value)
                            if not number.is_finite() or len(value) > 100 or abs(number.adjusted()) > 100 or abs(number.as_tuple().exponent) > 200: raise ValueError()
                            value = str(number)
                        elif kind == 'boolean':
                            if value.lower() not in ('true', 'false'): raise ValueError()
                            value = value.lower() == 'true'
                        row[key] = value
                    except (ValueError, InvalidOperation):
                        raise ValueError('Row %d, column %s: expected %s' % (line, key, kind))
                rows.append(row)
        except (StopIteration, csv.Error) as error:
            raise ValueError('Invalid CSV: ' + str(error)) from error
        table = {'name': name, 'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
                 'columns': [{'name': h, 'type': types.get(h, 'string'), 'nullable': True} for h in headers], 'rows': rows}
        return table

    def inspect(self, name, text):
        table = self._parse(name, text)
        return {'name': name, 'row_count': len(table['rows']),
                'columns': table['columns'], 'rows': table['rows'][:5],
                'truncated': len(table['rows']) > 5}

    def add(self, name, text, types=None):
        return self._persist(self._parse(name, text, types))

    def _persist(self, table):
        raw = json.dumps(table, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        ident = hashlib.sha256(raw).hexdigest()
        with self.lock:
            path = self._path(ident)
            if not path.exists():
                if len(list(self.root.glob('*.json'))) >= 100: raise ValueError('Workspace limit is 100 table artifacts')
                temp = path.with_suffix('.tmp')
                temp.write_bytes(raw)
                temp.replace(path)
        return self.metadata(ident, table)

    def preview(self, ident):
        table = self.read(ident)
        return dict(self.metadata(ident, table), rows=table['rows'][:20], truncated=len(table['rows']) > 20)

    def summarize(self, reference, column):
        if not isinstance(reference, dict) or reference.get('type') != 'table_ref':
            raise ValueError('Data summary requires a table_ref from the Data workspace')
        table = self.read(reference.get('id'))
        schema = {c['name']: c['type'] for c in table['columns']}
        if schema.get(column) not in ('integer', 'decimal'):
            raise ValueError('Choose an integer or decimal column for the summary')
        values = [Decimal(str(row[column])) for row in table['rows'] if row[column] is not None]
        return dict(self._statistics(values, len(table['rows'])),
                    source=self.metadata(reference['id'], table), column=column)

    @staticmethod
    def _statistics(values, row_count):
        # Align all digits and reserve enough carry places for every row.
        precision = (max(v.adjusted() for v in values) -
                     min(v.as_tuple().exponent for v in values) +
                     len(str(len(values))) + 2) if values else 1
        with localcontext() as context:
            context.prec = max(1, precision)
            total = sum(values, Decimal(0))
        return {'row_count': row_count, 'count': len(values),
                'null_count': row_count - len(values), 'sum': str(total),
                'min': str(min(values)) if values else None,
                'max': str(max(values)) if values else None}

    def group(self, reference, group_column, column, null_keys='include', max_groups=100):
        """One typed group key; results stay in a bounded immutable table."""
        if not isinstance(reference, dict) or reference.get('type') != 'table_ref':
            raise ValueError('Grouped summary requires a table_ref')
        if isinstance(max_groups, bool) or not isinstance(max_groups, int) or not 1 <= max_groups <= 500:
            raise ValueError('Group limit must be between 1 and 500')
        if null_keys not in ('include','exclude'):
            raise ValueError('Choose include or exclude for null group keys')
        table = self.read(reference.get('id'))
        schema = {c['name']: c['type'] for c in table['columns']}
        if not isinstance(group_column, str) or group_column not in schema:
            raise ValueError('Group column does not exist in the source table')
        if not isinstance(column, str) or schema.get(column) not in ('integer','decimal'):
            raise ValueError('Choose an integer or decimal column to aggregate')
        groups, excluded = {}, 0
        for row in table['rows']:
            key = row[group_column]
            if key is None and null_keys == 'exclude':
                excluded += 1
                continue
            # Numeric equivalents (0.1 and 0.10) share one decimal group.
            identity = Decimal(key) if key is not None and schema[group_column] == 'decimal' else key
            if identity not in groups:
                if len(groups) >= max_groups:
                    raise ValueError('Group limit exceeded; filter the table first or increase the limit (maximum 500)')
                groups[identity] = {'key':key, 'rows':0, 'values':[]}
            bucket = groups[identity]
            bucket['rows'] += 1
            if row[column] is not None: bucket['values'].append(Decimal(str(row[column])))
        rows = [dict(self._statistics(g['values'],g['rows']),group_key=g['key']) for g in groups.values()]
        columns = [{'name':'group_key','type':schema[group_column],'nullable':True}]
        columns += [{'name':name,'type':'integer','nullable':False} for name in ('row_count','count','null_count')]
        columns += [{'name':name,'type':'decimal','nullable':name != 'sum'} for name in ('sum','min','max')]
        return self._persist({'name':('grouped-'+table['name'])[-200:], 'columns':columns, 'rows':rows,
                              'source_sha256':table['source_sha256'],
                              'provenance':{'operation':'group','parent_id':reference['id'],
                                            'group_column':group_column,'column':column,'null_keys':null_keys,
                                            'max_groups':max_groups,'source_rows':len(table['rows']),
                                            'excluded_null_keys':excluded,'group_count':len(rows)}})

    def filter(self, reference, column, operator, value=None):
        """Typed comparisons; null cells only match explicit null operators."""
        if not isinstance(reference, dict) or reference.get('type') != 'table_ref':
            raise ValueError('Table filter requires a table_ref from the Data workspace')
        table = self.read(reference.get('id'))
        schema = {c['name']: c['type'] for c in table['columns']}
        if not isinstance(column, str) or column not in schema:
            raise ValueError('Filter column does not exist in the source table')
        kind = schema[column]
        operators = ('eq','ne','gt','gte','lt','lte','contains','is_null','not_null')
        if operator not in operators: raise ValueError('Unsupported filter operator')
        if operator in ('gt','gte','lt','lte') and kind not in ('integer','decimal'):
            raise ValueError('Ordered comparisons require an integer or decimal column')
        if operator == 'contains' and kind != 'string':
            raise ValueError('Contains requires a text column')
        expected = None
        if operator not in ('is_null','not_null'):
            if not isinstance(value, str) or not value or len(value) > 4096:
                raise ValueError('Comparison value must be nonempty text up to 4096 characters; use Is null for empty cells')
            # Use the import conversion contract rather than a second coercion rule.
            wire = io.StringIO()
            writer = csv.writer(wire)
            writer.writerow([column]); writer.writerow([value])
            expected = self._parse('comparison.csv', wire.getvalue(), {column:kind})['rows'][0][column]
            if kind == 'decimal': expected = Decimal(expected)
        def matches(row):
            actual = row[column]
            if operator == 'is_null': return actual is None
            if operator == 'not_null': return actual is not None
            if actual is None: return False
            if kind == 'decimal': actual = Decimal(actual)
            if operator == 'eq': return actual == expected
            if operator == 'ne': return actual != expected
            if operator == 'gt': return actual > expected
            if operator == 'gte': return actual >= expected
            if operator == 'lt': return actual < expected
            if operator == 'lte': return actual <= expected
            return expected in actual
        rows = [row for row in table['rows'] if matches(row)]
        derived = {'name': ('filtered-' + table['name'])[-200:],
                   'columns': table['columns'], 'rows': rows,
                   'source_sha256': table['source_sha256'],
                   'provenance': {'operation':'filter', 'parent_id':reference['id'],
                                  'column':column, 'operator':operator,
                                  'value':value if operator not in ('is_null','not_null') else None,
                                  'source_rows':len(table['rows']), 'matched_rows':len(rows)}}
        return self._persist(derived)

    def reconcile(self, left_ref, right_ref, left_key, right_key, left_column, right_column,
                  duplicates='reject', null_keys='reject', max_rows=10000):
        """Bounded full outer comparison of one key and one value per side."""
        if duplicates not in ('reject','first','last') or null_keys not in ('reject','exclude'):
            raise ValueError('Choose a supported duplicate and null-key policy')
        if isinstance(max_rows,bool) or not isinstance(max_rows,int) or not 1 <= max_rows <= self.MAX_ROWS:
            raise ValueError('Reconciliation row limit must be between 1 and 20000')
        tables = []
        for reference in (left_ref,right_ref):
            if not isinstance(reference,dict) or reference.get('type') != 'table_ref':
                raise ValueError('Reconciliation requires two table_ref inputs')
            tables.append(self.read(reference.get('id')))
        left,right = tables
        schemas = [{c['name']:c['type'] for c in table['columns']} for table in tables]
        for schema,key,column in zip(schemas,(left_key,right_key),(left_column,right_column)):
            if not isinstance(key,str) or key not in schema or not isinstance(column,str) or column not in schema:
                raise ValueError('Mapped key or value column does not exist')
        def compatible(a,b):
            return a == b or (a in ('integer','decimal') and b in ('integer','decimal'))
        key_types = [schemas[0][left_key],schemas[1][right_key]]
        value_types = [schemas[0][left_column],schemas[1][right_column]]
        if not compatible(*key_types) or not compatible(*value_types):
            raise ValueError('Mapped columns must have matching types or both be numeric')
        numeric_key = key_types[0] in ('integer','decimal')
        numeric_value = value_types[0] in ('integer','decimal')
        def index(table,key,side):
            items, duplicate_count, excluded = {},0,0
            for row in table['rows']:
                value = row[key]
                if value is None:
                    if null_keys == 'reject': raise ValueError(side + ' table has a null key; choose Exclude null keys or fix the source')
                    excluded += 1
                    continue
                identity = Decimal(str(value)) if numeric_key else value
                if identity in items:
                    duplicate_count += 1
                    if duplicates == 'reject': raise ValueError(side + ' table has duplicate keys; choose First or Last explicitly or fix the source')
                    if duplicates == 'first': continue
                items[identity] = row
            return items,duplicate_count,excluded
        li,ld,ln = index(left,left_key,'Left')
        ri,rd,rn = index(right,right_key,'Right')
        keys = list(li) + [k for k in ri if k not in li]
        if len(keys) > max_rows: raise ValueError('Reconciliation row limit exceeded; filter sources or increase the limit')
        rows,counts = [],dict.fromkeys(('matched','changed','left_only','right_only'),0)
        for key in keys:
            l,r = li.get(key),ri.get(key)
            lv = l[left_column] if l is not None else None
            rv = r[right_column] if r is not None else None
            a = Decimal(str(lv)) if numeric_value and lv is not None else lv
            b = Decimal(str(rv)) if numeric_value and rv is not None else rv
            status = 'right_only' if l is None else 'left_only' if r is None else 'matched' if a == b else 'changed'
            delta = self._statistics([a,b.copy_negate()],2)['sum'] if numeric_value and a is not None and b is not None else None
            counts[status] += 1
            rows.append({'key':str(key) if numeric_key else key,
                         'left_value':str(a) if numeric_value and a is not None else a,
                         'right_value':str(b) if numeric_value and b is not None else b,
                         'left_present':l is not None,'right_present':r is not None,'status':status,'delta':delta})
        key_type = 'decimal' if numeric_key else key_types[0]
        value_type = 'decimal' if numeric_value else value_types[0]
        columns = [{'name':'key','type':key_type,'nullable':False}]
        columns += [{'name':name,'type':value_type,'nullable':True} for name in ('left_value','right_value')]
        columns += [{'name':name,'type':'boolean','nullable':False} for name in ('left_present','right_present')]
        columns += [{'name':'status','type':'string','nullable':False},{'name':'delta','type':'decimal','nullable':True}]
        provenance = {'operation':'reconcile','parent_ids':[left_ref['id'],right_ref['id']],
                      'left_key':left_key,'right_key':right_key,'left_column':left_column,'right_column':right_column,
                      'duplicates':duplicates,'null_keys':null_keys,'max_rows':max_rows,
                      'left_duplicates':ld,'right_duplicates':rd,'left_null_keys_excluded':ln,'right_null_keys_excluded':rn}
        source_hash = hashlib.sha256((left['source_sha256']+':'+right['source_sha256']).encode()).hexdigest()
        reference = self._persist({'name':'reconciled.csv','columns':columns,'rows':rows,
                                   'source_sha256':source_hash,'provenance':provenance})
        return {'table':reference,'summary':dict(counts,total_rows=len(rows),left_duplicates=ld,right_duplicates=rd,
                                               left_null_keys_excluded=ln,right_null_keys_excluded=rn)}
