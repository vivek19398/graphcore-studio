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
                'source_sha256': table['source_sha256']}

    def list(self):
        with self.lock:
            return [self.metadata(p.stem, self.read(p.stem))
                    for p in sorted(self.root.glob('*.json'))]

    def add(self, name, text, types=None):
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
        # Align the full exponent range, allowing for carry from every row.
        precision = (max(v.adjusted() for v in values) -
                     min(v.as_tuple().exponent for v in values) +
                     len(str(len(values))) + 2) if values else 1
        with localcontext() as context:
            context.prec = max(1, precision)
            total = sum(values, Decimal(0))
        return {'source': self.metadata(reference['id'], table), 'column': column,
                'count': len(values), 'null_count': len(table['rows']) - len(values),
                'sum': str(total), 'min': str(min(values)) if values else None,
                'max': str(max(values)) if values else None}
