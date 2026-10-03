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
