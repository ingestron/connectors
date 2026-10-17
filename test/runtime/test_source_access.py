import csv
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
import source_access as access


class Cursor:
    def __init__(self): self.queries = []
    def execute(self, sql, parameters=()): self.queries.append((sql, parameters))
    def fetchone(self): return [1]
    def fetchmany(self, count): return [('dbo', 'Orders'), ('dbo', 'Products'), ('dbo', 'Returns')][:count]


class Database:
    def __init__(self): self.c = Cursor(); self.closed = False
    def cursor(self): return self.c
    def close(self): self.closed = True


class SourceAccess(unittest.TestCase):
    def request(self, kind='sql-server', action='test', **args):
        settings = {'connection': {'server': 'db.example.invalid', 'database': 'retail',
                    'authentication': {'method': 'sql-password', 'username': 'reader', 'password': {'$secret': {'env': 'DEMO_PASSWORD'}}}}}
        return {'connector': kind, 'action': action, 'settings': settings, **args}

    def setUp(self):
        self.socket = patch.object(socket, 'create_connection', side_effect=AssertionError('No external network')); self.socket.start()
        self.secret = patch.dict(os.environ, {'DEMO_PASSWORD': 'synthetic-only'}); self.secret.start()
    def tearDown(self): self.socket.stop(); self.secret.stop()

    def test_database_probe_never_reads_tables(self):
        for kind in ('sql-server', 'postgresql', 'mysql', 'oracle'):
            db = Database()
            req = self.request(kind)
            if kind != 'sql-server': req['settings'] = {'connection': {'host': 'db.example.invalid', 'service' if kind == 'oracle' else 'database': 'retail', 'user': 'reader', 'password': {'$secret': {'env': 'DEMO_PASSWORD'}}}}
            result = access.execute(req, connect=lambda *a, **k: db)
            self.assertEqual(result['status'], 'succeeded', result)
            self.assertEqual(db.c.queries, [('SELECT 1 FROM dual' if kind == 'oracle' else 'SELECT 1', ())])
            self.assertTrue(db.closed)
            self.assertNotIn('synthetic-only', json.dumps(result))

    def test_database_listing_is_bounded_permission_filtered_and_redacted(self):
        db = Database()
        db.c.fetchmany = lambda count: [('master',), ('retail',)][:count]
        result = access.execute(self.request(action='databases', limit=2), connect=lambda *a, **k: db)
        self.assertEqual(result['status'], 'succeeded', result)
        self.assertEqual(result['databases'], ['master', 'retail'])
        self.assertIn('TOP (2)', db.c.queries[0][0])
        self.assertIn('HAS_DBACCESS(name)=1', db.c.queries[0][0])
        self.assertTrue(db.closed)
        bad = access.execute(self.request(action='databases', limit=201), connect=lambda *a, **k: db)
        self.assertEqual(bad['status'], 'failed')
        self.assertNotIn('databases', bad)
        denied = access.execute(self.request(action='databases'), connect=lambda *a, **k: (_ for _ in ()).throw(ValueError('synthetic-only')))
        self.assertNotIn('synthetic-only', json.dumps(denied))

    def test_sql_schema_reader_uses_only_system_metadata(self):
        db = Database()
        db.c.fetchall = lambda: [('OrderID', 'int', 10, 0, False, True), ('Amount', 'decimal', 18, 2, True, False)]
        result = access.execute(self.request(action='metadata', tables=[{'schema':'dbo', 'table':'Orders'}]), connect=lambda *a, **k: db)
        self.assertEqual(result['status'], 'succeeded', result)
        self.assertEqual(result['tables'][0]['columns'][1]['type'], 'decimal')
        self.assertIn('FROM sys.tables', db.c.queries[0][0])
        self.assertEqual(db.c.queries[0][1], ('dbo', 'Orders'))
        self.assertTrue(db.closed)

    def test_inventory_keyset_is_bounded_and_search_is_literal(self):
        db = Database()
        result = access.execute(self.request(action='inventory', limit=2, query="x%' OR 1=1--", schema='dbo'), connect=lambda *a, **k: db)
        self.assertEqual(len(result['tables']), 2)
        self.assertEqual(json.loads(result['nextCursor']), ['dbo', 'Products'])
        sql, parameters = db.c.queries[0]
        self.assertIn('TOP (3)', sql)
        self.assertNotIn('OR 1=1--', sql)
        self.assertIn("%x!%' OR 1=1--%", parameters)
        self.assertTrue(db.closed)

    def test_bad_cursor_and_upstream_errors_are_redacted(self):
        db = Database()
        result = access.execute(self.request(action='inventory', cursor='not-json'), connect=lambda *a, **k: db)
        self.assertEqual(result['status'], 'failed'); self.assertTrue(db.closed)
        result = access.execute(self.request(), connect=lambda *a, **k: (_ for _ in ()).throw(ValueError('synthetic-only https://credential')))
        self.assertNotIn('synthetic-only', json.dumps(result)); self.assertNotIn('credential', json.dumps(result))

    def test_file_header_only_and_json_requires_explicit_sampling(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder).resolve() / 'data.csv'; path.write_text('id,name\nthis is a broken row with secret business value\n')
            result = access.execute({'connector': 'files', 'action': 'metadata', 'settings': {}, 'tables': [{'path': str(path), 'format': 'csv'}]})
            self.assertEqual(result['status'], 'succeeded', result)
            self.assertEqual([c['name'] for c in result['tables'][0]['columns']], ['id', 'name'])
            self.assertNotIn('business', json.dumps(result))
            path = Path(folder).resolve() / 'data.json'; path.write_text('[{"business": "hidden"}]')
            result = access.execute({'connector': 'files', 'action': 'metadata', 'settings': {}, 'tables': [{'path': str(path), 'format': 'json'}]})
            self.assertEqual(result['code'], 'SAMPLING_REQUIRED'); self.assertEqual(result['status'], 'unsupported')

    def test_http_probes_use_metadata_and_never_download_records(self):
        sas = 'sv=2023-11-03&sp=rl&se=2099-01-01&spr=https&sig=synthetic'
        with patch.object(access, 'api', return_value=b'{}') as send:
            self.assertEqual(access.probe('azure-blob', {'account':'retaildemo', 'container':'bronze', 'sas_token':sas}), 'metadata')
            self.assertEqual(send.call_args.args[0], 'retaildemo.blob.core.windows.net')
            self.assertIn('restype=container&comp=list&maxresults=1', send.call_args.args[1]); self.assertEqual(send.call_args.args[3], 'GET')
            access.probe('azure-blob', {'account':'retaildemo', 'container':'bronze', 'sas_token':sas}, {'path':'orders.parquet'})
            self.assertIn('/bronze/orders.parquet?', send.call_args.args[1]); self.assertEqual(send.call_args.args[3], 'HEAD')
            self.assertEqual(access.probe('stripe', {'api_key':'sk_test_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'}), 'authentication')
            self.assertEqual(send.call_args.args[:2], ('api.stripe.com', '/v1/account'))
            self.assertEqual(access.probe('github', {'repositories':['example/retail'], 'authentication':'token', 'auth_token':'synthetic-only'}), 'metadata')
            self.assertEqual(send.call_args.args[:2], ('api.github.com', '/repos/example/retail'))
            self.assertEqual(send.call_args.args[2]['Authorization'], 'Bearer synthetic-only')
        with patch.object(access, 'api') as send:
            result=access.execute({'connector':'github','action':'test','settings':{'authentication':'token','repositories':['example/retail']}})
            self.assertEqual(result['code'], 'SECRET_MISSING'); send.assert_not_called()
        for kind in ('s3','gcs'):
            with patch('object_store_reader.request', return_value=(b'', None)) as send:
                self.assertEqual(access.probe(kind, {'bucket':'bronze'}), 'metadata')
                self.assertEqual(send.call_args.args, (kind.upper(), {'bucket':'bronze'}, kind, 'HEAD', ''))
        with patch('sftp_reader.OpenSsh') as client:
            self.assertEqual(access.probe('sftp', {'host':'sftp.example.invalid'}), 'connection')
            client.return_value.run.assert_called_once_with(['pwd'])

    def test_graph_and_application_probes_use_only_metadata(self):
        base={'tenant_id':'11111111-1111-1111-1111-111111111111', 'client_id':'22222222-2222-2222-2222-222222222222', 'client_secret':'synthetic-only'}
        with patch('graph_reader.token', return_value='synthetic-token'), patch('graph_reader.graph', return_value={}) as graph:
            access.probe('sharepoint', {**base, 'site':'https://retail.sharepoint.com/sites/finance'})
            self.assertEqual(graph.call_args.args[1], '/v1.0/sites/retail.sharepoint.com:/sites/finance')
            access.probe('onedrive', {**base, 'user':'reader@example.invalid'})
            self.assertEqual(graph.call_args.args[1], '/v1.0/users/reader@example.invalid/drive')
        with patch('salesforce_reader.token', return_value='synthetic-token'), patch('salesforce_reader.describe', return_value={}) as describe:
            access.probe('salesforce', {'instance_url':'https://retail.my.salesforce.com','client_id':'demo','client_secret':'synthetic-only'})
            describe.assert_called_once_with('retail.my.salesforce.com','synthetic-token','Account')
        with patch('hubspot_reader.properties', return_value={}) as properties:
            access.probe('hubspot', {'access_token':'synthetic-only'})
            properties.assert_called_once_with('synthetic-only','contacts')
        with patch('jira_reader.issue_fields', return_value={}) as fields:
            access.probe('jira', {'site':'https://retail.atlassian.net','email':'reader@example.invalid','api_token':'synthetic-only'})
            self.assertEqual(fields.call_args.args[0], 'retail.atlassian.net')
        result=access.execute({'connector':'unknown','action':'test','settings':{}})
        self.assertEqual(result['status'], 'unsupported')

    def test_http_failure_never_echoes_credentials_or_body(self):
        connection=Mock(); response=Mock(status=403); connection.getresponse.return_value=response
        with patch.object(access.http.client,'HTTPSConnection',return_value=connection):
            result=access.execute({'connector':'github','action':'test','settings':{'repositories':['example/retail'],'authentication':'token','auth_token':'synthetic-only'}})
        self.assertEqual(result['code'], 'ACCESS_FORBIDDEN'); response.read.assert_not_called(); connection.close.assert_called_once()
        self.assertNotIn('synthetic-only', json.dumps(result))

    def test_declared_catalogue_does_not_claim_account_permissions(self):
        result = access.execute({'connector': 'stripe', 'action': 'inventory', 'settings': {}})
        self.assertEqual(result['code'], 'DECLARED_OBJECTS')
        with patch('stripe_reader.scan', side_effect=AssertionError('Must not read records')):
            result = access.execute({'connector': 'stripe', 'action': 'metadata', 'settings': {}, 'tables': [{'object': 'customers'}]})
        self.assertEqual(result['code'], 'DECLARED_SCHEMA')

class GitHubMetadata(unittest.TestCase):
    def test_declared_issues_inventory_is_bounded_and_never_reads_records(self):
        with patch.object(access, 'api', side_effect=AssertionError('No REST records')):
            response = access.execute({'connector': 'github', 'action': 'inventory', 'settings': {}, 'query': ''})
            self.assertEqual(response['code'], 'DECLARED_OBJECTS')
            self.assertEqual(response['tables'][0]['source'], {'stream': 'issues'})
            response = access.execute({'connector': 'github', 'action': 'inventory', 'settings': {}, 'query': 'missing'})
            self.assertEqual(response['tables'], [])

    def test_pinned_issue_schema_excludes_nested_fields_and_does_not_fetch_rows(self):
        with patch.object(socket, 'create_connection', side_effect=AssertionError('No external reads')):
            result = access.execute({'connector': 'github', 'action': 'metadata', 'settings': {'authentication': 'anonymous', 'repositories': ['demo/repo']}, 'tables': [{'stream': 'issues'}]})
        self.assertEqual(result['status'], 'succeeded', result)
        self.assertEqual(result['code'], 'DECLARED_SCHEMA')
        columns = {c['name']: c for c in result['tables'][0]['columns']}
        self.assertEqual(columns['id']['type'], 'integer')
        self.assertEqual(columns['title']['type'], 'string')
        self.assertFalse(columns['user']['supported'])
        self.assertEqual(result['tables'][0]['source'], {'stream': 'issues'})
        self.assertNotIn('record', json.dumps(result))
        result = access.execute({'connector': 'github', 'action': 'metadata', 'settings': {'authentication': 'anonymous', 'repositories': ['demo/repo']}, 'tables': [{'stream': 'repositories'}]})
        self.assertEqual(result['status'], 'failed')

class SQLFailureCategories(unittest.TestCase):
    def test_known_driver_failures_are_categorised_without_returning_private_text(self):
        cases = {'28000 18456': 'SQL_AUTH', '42000 4060':'SQL_DATABASE', '40615':'SQL_FIREWALL', '40613':'SQL_UNAVAILABLE', 'HYT00':'SQL_TIMEOUT', '08001':'SQL_NETWORK', 'unknown':'SQL_CONNECT', 'TCP Provider: Error code 0x2AF9':'SQL_DNS', 'SSL Provider certificate verify failed':'SQL_TLS'}
        for error, code in cases.items():
            def fail(*a, **k): raise Exception(error + ' password=synthetic-private-value server=private-host')
            with self.assertRaises(access.AccessError) as caught:
                access.database_connection('sql-server', {'connection': {'server':'db.example.invalid','database':'retail','authentication':{'method':'sql-password','username':'reader','password':'synthetic'}}}, connect=fail)
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn('synthetic-private-value', str(caught.exception))
