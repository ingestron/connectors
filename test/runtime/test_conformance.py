"""Existing connectors run the shared conformance suite (PB-064 phase 3)."""
import re
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'conformance'))
from harness import Conformance, singer_runtime
_before = (singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review)
import files_table_runtime
import sql_server_runtime
singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review = _before


class FilesConformance(Conformance, unittest.TestCase):
    def make_connector(self):
        self.directory = tempfile.TemporaryDirectory()
        # macOS temporary directories sit behind a symlink the reader refuses.
        self.root = Path(self.directory.name).resolve()
        self.addCleanup(self.directory.cleanup)
        return files_table_runtime.Files()

    def settings(self):
        return {}

    def tables(self):
        return {
            'customers': {'source': {'path': str(self.root / 'customers.csv'), 'format': 'csv'},
                          'columns': [{'name': 'id', 'type': 'BIGINT'}, {'name': 'name', 'type': 'STRING'}]},
            'orders': {'source': {'path': str(self.root / 'orders.csv'), 'format': 'csv'},
                       'columns': [{'name': 'amount', 'type': 'DECIMAL(10,2)'}]},
        }

    def rows(self, stream):
        return [{'id': 1, 'name': 'Ada'}, {'id': 2, 'name': 'Grace'}] if stream == 'customers' \
            else [{'amount': '12.50'}]

    def load(self, stream, rows):
        header = ['id', 'name'] if stream == 'customers' else ['amount']
        lines = [','.join(header)] + [','.join(str(r[h]) for h in header) for r in rows]
        (self.root / f'{stream}.csv').write_text('\n'.join(lines) + '\n')

    def change_schema(self, stream):
        (self.root / f'{stream}.csv').write_text('id,name,extra\n1,Ada,x\n')

    def break_source(self, stream):
        (self.root / f'{stream}.csv').unlink()

    def secret_values(self):
        return []


class FakeSql:
    """An in-memory SQL Server: metadata and projection queries only."""

    def __init__(self):
        self.tables, self.fail = {}, set()

    def connect(self, conn_string, timeout=None):
        return self

    def cursor(self):
        return self

    def close(self):
        pass

    def execute(self, query, parameters=None):
        if parameters:
            self.current = self.tables.get(parameters[1])
            self.position = 0
            return
        table = re.search(r'FROM \[[^\]]+\]\.\[([^\]]+)\]', query).group(1)
        if table in self.fail:
            raise RuntimeError('network reset while reading secret-row-value')
        self.current, self.position = self.tables[table], 0

    def fetchall(self):
        return self.current['columns'] if self.current else []

    def fetchmany(self, size):
        rows = self.current['rows'][self.position:self.position + size]
        self.position += len(rows)
        return rows


class SqlServerConformance(Conformance, unittest.TestCase):
    def make_connector(self):
        self.database = FakeSql()
        return sql_server_runtime.SqlServer(connect=self.database.connect)

    def settings(self):
        return {'connection': {'server': 'sql.example.invalid', 'database': 'sales',
                               'authentication': {'method': 'sql-password', 'username': 'reader',
                                                  'password': 'p4ss-secret'}}}

    def tables(self):
        return {'Products': {'source': {'schema': 'dbo', 'table': 'Products'},
                             'columns': [{'name': 'ProductID', 'type': 'BIGINT'}]},
                'Orders': {'source': {'schema': 'dbo', 'table': 'Orders'},
                           'columns': [{'name': 'OrderID', 'type': 'BIGINT'},
                                       {'name': 'Total', 'type': 'DECIMAL(10,2)'}]}}

    def rows(self, stream):
        return [(1,), (2,)] if stream == 'Products' else [(10, Decimal('5.00'))]

    def load(self, stream, rows):
        columns = [('ProductID', 'int', 10, 0, False)] if stream == 'Products' else \
            [('OrderID', 'int', 10, 0, False), ('Total', 'decimal', 10, 2, True)]
        self.database.tables[stream] = {'columns': columns, 'rows': rows}

    def change_schema(self, stream):
        self.database.tables[stream]['columns'] = [
            (name, 'nvarchar', 0, 0, True) for name, *_ in self.database.tables[stream]['columns']]

    def break_source(self, stream):
        self.database.fail.add(stream)

    def secret_values(self):
        return ['p4ss-secret', 'secret-row-value']


if __name__ == '__main__':
    unittest.main()
