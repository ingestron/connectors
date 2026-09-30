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
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mocks'))
from harness import Conformance, singer_runtime
from stripe_api import StripeApi
from graph_api import GraphApi, TENANT, CLIENT
_before = (singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review)
import azure_blob_runtime
import files_table_runtime
import sql_server_runtime
import stripe_runtime
import graph_runtime
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

STRIPE_KEY = 'rk_test_' + 'SyntheticKey0123456789'


class StripeConformance(Conformance, unittest.TestCase):
    """Stripe against an in-memory list API that follows the documented pagination."""

    def make_connector(self):
        self.api = StripeApi(STRIPE_KEY)
        transport = patch('stripe_reader.http.client.HTTPSConnection', self.api.connection())
        transport.start()
        self.addCleanup(transport.stop)
        return stripe_runtime.Stripe()

    def settings(self):
        return {'api_key': STRIPE_KEY}

    def tables(self):
        return {
            'customers': {'source': {'object': 'customers'},
                          'columns': [{'name': 'id', 'type': 'STRING'}, {'name': 'email', 'type': 'STRING'},
                                      {'name': 'balance', 'type': 'BIGINT'},
                                      {'name': 'delinquent', 'type': 'BOOLEAN'}]},
            'charges': {'source': {'object': 'charges'},
                        'columns': [{'name': 'id', 'type': 'STRING'}, {'name': 'amount', 'type': 'BIGINT'},
                                    {'name': 'currency', 'type': 'STRING'}]},
        }

    def rows(self, stream):
        if stream == 'customers':
            # More than one page, so pagination is exercised.
            return [{'id': f'cus_{i:04d}', 'object': 'customer', 'email': None if i % 7 == 0 else f'c{i}@example.invalid',
                     'balance': i, 'delinquent': i % 2 == 0, 'created': 1_700_000_000 + i, 'livemode': False}
                    for i in range(230)]
        return [{'id': 'ch_1', 'object': 'charge', 'amount': 1250, 'currency': 'nzd', 'created': 1_700_000_000,
                 'livemode': False}]

    def load(self, stream, rows):
        self.api.load(stream, rows)

    def change_schema(self, stream):
        self.api.load(stream, [{**row, 'balance': str(row['balance'])} for row in self.rows(stream)])

    def break_source(self, stream):
        self.api.fail[stream] = 500

    def secret_values(self):
        return [STRIPE_KEY, 'secret-row-value']

GRAPH_SECRET = 'graph-client-' + 'secret-value'


class SharePointConformance(Conformance, unittest.TestCase):
    """SharePoint through a Graph mock: one file table and one folder table read across two pages."""

    def make_connector(self):
        self.api = GraphApi(GRAPH_SECRET)
        transport = patch('graph_reader.http.client.HTTPSConnection', self.api.connection())
        transport.start()
        self.addCleanup(transport.stop)
        return graph_runtime.GraphFiles('sharepoint')

    def settings(self):
        return {'tenant_id': TENANT, 'client_id': CLIENT, 'client_secret': GRAPH_SECRET,
                'site': 'https://contoso.sharepoint.com/sites/finance'}

    def tables(self):
        return {
            'customers': {'source': {'path': 'Shared Documents/retail/customers.csv', 'format': 'csv'},
                          'columns': [{'name': 'id', 'type': 'BIGINT'}, {'name': 'name', 'type': 'STRING'}]},
            'orders': {'source': {'path': 'Shared Documents/retail/orders', 'format': 'csv'},
                       'columns': [{'name': 'amount', 'type': 'DECIMAL(10,2)'}]},
        }

    def rows(self, stream):
        return [{'id': 1, 'name': 'Ada'}, {'id': 2, 'name': 'Grace'}] if stream == 'customers' \
            else [{'amount': '12.50'}, {'amount': '3.00'}, {'amount': '7.25'}]

    def load(self, stream, rows):
        drive = self.api.drives['drive-docs']
        for path in [p for p in drive if p.startswith(f'retail/{stream}')]:
            del drive[path]
        if stream == 'customers':
            text = 'id,name\n' + ''.join(f"{r['id']},{r['name']}\n" for r in rows)
            self.api.put('drive-docs', 'retail/customers.csv', text.encode())
            return
        # One file per row across a paged folder, plus a file of another format that is ignored.
        for i, row in enumerate(rows or [None]):
            text = 'amount\n' + (f"{row['amount']}\n" if row else '')
            self.api.put('drive-docs', f'retail/orders/part-{i}.csv', text.encode())
        self.api.put('drive-docs', 'retail/orders/readme.txt', b'not data')

    def change_schema(self, stream):
        self.api.put('drive-docs', 'retail/customers.csv', b'id,name,extra\n1,Ada,x\n')

    def break_source(self, stream):
        self.api.fail['retail/orders/part-1.csv'] = 500

    def secret_values(self):
        return [GRAPH_SECRET, 'secret-tempauth', 'secret-row-value', 'graph-access-token']


if __name__ == '__main__':
    unittest.main()
