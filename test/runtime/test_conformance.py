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
from saas_api import SalesforceApi, HubSpotApi, JiraApi
from s3_api import S3Api
_before = (singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review)
import azure_blob_runtime
import files_table_runtime
import sql_server_runtime
import stripe_runtime
import graph_runtime
import salesforce_runtime
import hubspot_runtime
import jira_runtime
import object_store_runtime
import sftp_runtime
import sftp_reader
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
        self.keys = 'is_primary_key' in query
        if parameters:
            self.current = self.tables.get(parameters[1])
            self.position = 0
            return
        table = re.search(r'FROM \[[^\]]+\]\.\[([^\]]+)\]', query).group(1)
        if table in self.fail:
            raise RuntimeError('network reset while reading secret-row-value')
        self.current, self.position = self.tables[table], 0

    def fetchall(self):
        if not self.current: return []
        # The catalogue query adds a primary-key flag; the first column is the key here.
        return [(*c, int(i == 0)) for i, c in enumerate(self.current['columns'])] if self.keys \
            else self.current['columns']

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

SF_SECRET, HS_TOKEN, JIRA_TOKEN = 'sf-client-' + 'secret', 'pat-na1-' + 'synthetic-token', 'jira-' + 'api-token'


class ApiConformance(Conformance):
    """Shared wiring: patch the reader's HTTPS client with an in-memory API."""
    module = None

    def patch_api(self, api):
        self.api = api
        transport = patch('rest_client.http.client.HTTPSConnection', api.connection())
        transport.start()
        self.addCleanup(transport.stop)


class SalesforceConformance(ApiConformance, unittest.TestCase):
    def make_connector(self):
        self.patch_api(SalesforceApi('client-id', SF_SECRET))
        return salesforce_runtime.Salesforce()

    def settings(self):
        return {'instance_url': 'https://acme.my.salesforce.com', 'client_id': 'client-id',
                'client_secret': SF_SECRET}

    def tables(self):
        return {'accounts': {'source': {'object': 'Account'},
                             'columns': [{'name': 'Id', 'type': 'STRING'}, {'name': 'Name', 'type': 'STRING'},
                                         {'name': 'AnnualRevenue', 'type': 'DECIMAL(18,2)'}]},
                'invoices': {'source': {'object': 'Invoice__c'},
                             'columns': [{'name': 'Id', 'type': 'STRING'}, {'name': 'Paid__c', 'type': 'BOOLEAN'}]}}

    def rows(self, stream):
        if stream == 'accounts':
            return [{'Id': f'001{i}', 'Name': f'A{i}', 'AnnualRevenue': 1000.5 + i} for i in range(5)]
        return [{'Id': 'a01', 'Paid__c': True}]

    def load(self, stream, rows):
        obj = 'Account' if stream == 'accounts' else 'Invoice__c'
        fields = {'Id': 'id', 'Name': 'string', 'AnnualRevenue': 'currency'} if stream == 'accounts' \
            else {'Id': 'id', 'Paid__c': 'boolean'}
        self.api.load(obj, fields, rows)

    def change_schema(self, stream):
        self.api.objects['Account']['fields'].pop('AnnualRevenue')

    def break_source(self, stream):
        self.api.fail['Invoice__c'] = 500

    def secret_values(self):
        return [SF_SECRET, 'secret-row-value', 'sf-access']


class HubSpotConformance(ApiConformance, unittest.TestCase):
    def make_connector(self):
        self.patch_api(HubSpotApi(HS_TOKEN))
        return hubspot_runtime.HubSpot()

    def settings(self):
        return {'access_token': HS_TOKEN}

    def tables(self):
        return {'contacts': {'source': {'object': 'contacts'},
                             'columns': [{'name': 'id', 'type': 'STRING'}, {'name': 'email', 'type': 'STRING'},
                                         {'name': 'num_employees', 'type': 'BIGINT'}]},
                'deals': {'source': {'object': 'deals'},
                          'columns': [{'name': 'id', 'type': 'STRING'}, {'name': 'amount', 'type': 'DECIMAL(18,2)'},
                                      {'name': 'archived', 'type': 'BOOLEAN'}]}}

    def rows(self, stream):
        if stream == 'contacts':
            return [{'id': str(i), 'email': f'c{i}@example.invalid', 'num_employees': str(i)} for i in range(5)]
        return [{'id': '9', 'amount': '12.50'}]

    def load(self, stream, rows):
        props = {'email': 'string', 'num_employees': 'number'} if stream == 'contacts' else {'amount': 'number'}
        self.api.load(stream, props, rows)

    def change_schema(self, stream):
        self.api.objects['contacts']['props']['num_employees'] = 'string'

    def break_source(self, stream):
        self.api.fail['deals'] = 503

    def secret_values(self):
        return [HS_TOKEN, 'secret-row-value']


class JiraConformance(ApiConformance, unittest.TestCase):
    def make_connector(self):
        self.patch_api(JiraApi('reader@example.invalid', JIRA_TOKEN))
        self.api.fields = [{'id': 'summary', 'schema': {'type': 'string'}},
                           {'id': 'status', 'schema': {'type': 'status'}},
                           {'id': 'customfield_10016', 'schema': {'type': 'number'}}]
        return jira_runtime.Jira()

    def settings(self):
        return {'site': 'https://acme.atlassian.net', 'email': 'reader@example.invalid', 'api_token': JIRA_TOKEN}

    def tables(self):
        return {'issues': {'source': {'object': 'issues', 'jql': 'project = DEMO ORDER BY created ASC'},
                           'columns': [{'name': 'key', 'type': 'STRING'}, {'name': 'summary', 'type': 'STRING'},
                                       {'name': 'status', 'type': 'STRING'},
                                       {'name': 'customfield_10016', 'type': 'DECIMAL(10,1)'}]},
                'projects': {'source': {'object': 'projects'},
                             'columns': [{'name': 'id', 'type': 'STRING'}, {'name': 'key', 'type': 'STRING'},
                                         {'name': 'isPrivate', 'type': 'BOOLEAN'}]}}

    def rows(self, stream):
        if stream == 'issues':
            return [{'id': str(10000 + i), 'key': f'DEMO-{i}',
                     'fields': {'summary': f'Task {i}', 'status': {'name': 'To Do', 'id': '1'},
                                'customfield_10016': 3.0}} for i in range(5)]
        return [{'id': '10000', 'key': 'DEMO', 'isPrivate': False}, {'id': '10001', 'key': 'OPS', 'isPrivate': True},
                {'id': '10002', 'key': 'WEB', 'isPrivate': False}]

    def load(self, stream, rows):
        if stream == 'issues':
            self.api.issues = list(rows)
        else:
            self.api.tables['projects'] = ('/rest/api/3/project/search', True, list(rows))

    def change_schema(self, stream):
        self.api.fields = [f for f in self.api.fields if f['id'] != 'summary']

    def break_source(self, stream):
        self.api.fail['projects'] = 500

    def secret_values(self):
        return [JIRA_TOKEN, 'secret-row-value']

class S3Conformance(FilesConformance):
    """S3 through an in-memory ListObjectsV2/GetObject API; orders is a prefix of two objects."""
    kind, host, path_style = 's3', 'retail.s3.ap-southeast-2.amazonaws.com', False

    def make_connector(self):
        super().make_connector()
        self.api = S3Api('AKIA' + 'SYNTHETIC0001', self.host, 'retail', self.path_style)
        transport = patch('object_store_reader.http.client.HTTPSConnection', self.api.connection())
        transport.start()
        self.addCleanup(transport.stop)
        return object_store_runtime.ObjectStore(self.kind)

    def settings(self):
        return {'bucket': 'retail', 'region': 'ap-southeast-2', 'access_key_id': 'AKIA' + 'SYNTHETIC0001',
                'secret_access_key': 'synthetic-secret-key-value'}

    def tables(self):
        return {'customers': {'source': {'path': 'v1/customers.csv', 'format': 'csv'},
                              'columns': [{'name': 'id', 'type': 'BIGINT'}, {'name': 'name', 'type': 'STRING'}]},
                'orders': {'source': {'path': 'v1/orders', 'format': 'csv'},
                           'columns': [{'name': 'amount', 'type': 'DECIMAL(10,2)'}]}}

    def rows(self, stream):
        return super().rows(stream) + ([{'amount': '3.00'}, {'amount': '7.25'}] if stream == 'orders' else [])

    def load(self, stream, rows):
        if stream == 'customers':
            self.api.objects['v1/customers.csv'] = ('id,name\n' + ''.join(f"{r['id']},{r['name']}\n" for r in rows)).encode()
            return
        for key in [k for k in self.api.objects if k.startswith('v1/orders/')]:
            del self.api.objects[key]
        for i, row in enumerate(rows or [None]):
            self.api.objects[f'v1/orders/part-{i}.csv'] = ('amount\n' + (f"{row['amount']}\n" if row else '')).encode()
        self.api.objects['v1/orders/_SUCCESS'] = b''

    def change_schema(self, stream):
        self.api.objects['v1/customers.csv'] = b'id,name,extra\n1,Ada,x\n'

    def break_source(self, stream):
        self.api.fail['v1/orders/part-1.csv'] = 500

    def secret_values(self):
        return ['synthetic-secret-key-value', 'secret-row-value']


class GcsConformance(S3Conformance):
    kind, host, path_style = 'gcs', 'storage.googleapis.com', True

    def settings(self):
        return {'bucket': 'retail', 'access_key_id': 'AKIA' + 'SYNTHETIC0001',
                'secret_access_key': 'synthetic-secret-key-value'}

class LocalSftp:
    """A transport serving a local directory as the SFTP server's file system."""

    def __init__(self, root):
        self.root, self.fail = root, set()

    def list(self, path):
        target = self.root / path
        if target.is_file(): return [(target.name, target.stat().st_size, False)]
        if not target.is_dir(): raise sftp_reader.SftpError('SFTP_NOT_FOUND')
        return [(p.name, p.stat().st_size, p.is_dir()) for p in sorted(target.iterdir())]

    def get(self, remote, local):
        if remote in self.fail: raise sftp_reader.SftpError('SFTP_NOT_FOUND')
        Path(local).write_bytes((self.root / remote).read_bytes())


class SftpConformance(FilesConformance):
    def make_connector(self):
        super().make_connector()
        self.transport = LocalSftp(self.root)
        return sftp_runtime.Sftp(self.transport)

    def settings(self):
        return {'host': 'sftp.example.internal', 'user': 'reader', 'host_key': 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAISynthetic',
                'private_key': '-----BEGIN OPENSSH ' + 'PRIVATE KEY-----\nsynthetic-key-material\n-----END OPENSSH PRIVATE KEY-----'}

    def tables(self):
        return {'customers': {'source': {'path': 'customers.csv', 'format': 'csv'},
                              'columns': [{'name': 'id', 'type': 'BIGINT'}, {'name': 'name', 'type': 'STRING'}]},
                'orders': {'source': {'path': 'orders', 'format': 'csv'},
                           'columns': [{'name': 'amount', 'type': 'DECIMAL(10,2)'}]}}

    def load(self, stream, rows):
        if stream == 'customers':
            return super().load(stream, rows)
        folder = self.root / 'orders'
        folder.mkdir(exist_ok=True)
        for child in folder.iterdir():
            child.unlink()
        for i, row in enumerate(rows or [None]):
            (folder / f'part-{i}.csv').write_text('amount\n' + (f"{row['amount']}\n" if row else ''))

    def break_source(self, stream):
        self.transport.fail.add('orders/part-0.csv')

    def secret_values(self):
        return ['synthetic-key-material']


if __name__ == '__main__':
    unittest.main()
