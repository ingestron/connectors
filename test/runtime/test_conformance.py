"""Existing connectors run the shared conformance suite (PB-064 phase 3)."""
import re
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import hashlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'conformance'))
from harness import Conformance, singer_runtime
_before = (singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review)
import azure_blob_runtime
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


SAS = 'sv=2023-11-03&sp=r&se=2030-01-01&spr=https&sig=secret-signature'


class BlobResponse:
    def __init__(self, status, body=b'', etag=''):
        self.status, self.body = status, body
        self.headers = {'Content-Length': str(len(body)), 'ETag': etag}

    def getheader(self, key, default=None):
        return self.headers.get(key, default)

    def read(self, n):
        chunk, self.body = self.body[:n], self.body[n:]
        return chunk

    def close(self):
        pass


def blob_transport(root):
    """An HTTPS stand-in serving /<container>/<blob> from a local directory."""
    class Connection:
        def __init__(self, host, timeout):
            assert host == 'sampleaccount.blob.core.windows.net'

        def request(self, method, target, headers):
            path = root / target.split('?')[0].split('/', 2)[2]
            if not path.is_file():
                self.response = BlobResponse(404)
                return
            body = path.read_bytes()
            etag = '"' + hashlib.sha256(body).hexdigest() + '"'
            self.response = BlobResponse(200, body if method == 'GET' else b'', etag)
            self.response.headers['Content-Length'] = str(len(body))

        def getresponse(self):
            return self.response

        def close(self):
            pass
    return Connection


class AzureBlobConformance(FilesConformance):
    """Azure Blob shares the file reader; tables name blob paths in one container."""

    def make_connector(self):
        super().make_connector()
        http = patch('azure_blob_reader.http.client.HTTPSConnection', blob_transport(self.root))
        http.start()
        self.addCleanup(http.stop)
        return azure_blob_runtime.AzureBlob()

    def settings(self):
        return {'account': 'sampleaccount', 'container': 'samples', 'sas_token': SAS}

    def tables(self):
        tables = super().tables()
        for stream, table in tables.items():
            table['source']['path'] = f'{stream}.csv'
        return tables

    def secret_values(self):
        return ['secret-signature']


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
