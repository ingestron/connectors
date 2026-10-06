import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
import source_access as access
import source_sample as sampling

class Cursor:
    def __init__(self): self.queries = []; self.requested = []
    def execute(self, sql): self.queries.append(sql)
    def fetchmany(self, n): self.requested.append(n); return [(1, 'a' * 1000), (2, 'b'), (3, 'c')][:n]
class Database:
    def __init__(self): self.c = Cursor(); self.closed = False
    def cursor(self): return self.c
    def close(self): self.closed = True
class SourceSamples(unittest.TestCase):
    def setUp(self):
        self.sockets = patch.object(socket, 'create_connection', side_effect=AssertionError('No external sockets')); self.sockets.start()
    def tearDown(self): self.sockets.stop()
    def test_database_dialects_limit_quote_and_close(self):
        for kind in ('sql-server', 'postgresql', 'mysql', 'oracle'):
            db = Database()
            module = 'sql_server_reader' if kind == 'sql-server' else 'dbapi_reader'
            settings = {'connection': {'server': 'db.invalid', 'database': 'retail', 'authentication': {'method': 'sql-password', 'username': 'reader', 'password': 'synthetic'}}} if kind == 'sql-server' else {'connection': {'host':'db.invalid','service' if kind == 'oracle' else 'database':'retail','user':'reader','password':'synthetic'}}
            with patch(module + '.catalogue', return_value=[{'name':'id','type':'integer'}, {'name':'label','type':'string'}]):
                result = sampling.sample(kind, settings, {'source':{'schema':'sales', 'table':'Orders'},'limit':2}, connect=lambda *a, **k:db)
            self.assertEqual(result['rows'], [[1, 'a'*500], [2,'b']]);self.assertTrue(result['truncated']);self.assertTrue(db.closed)
            self.assertEqual(db.c.requested, [3]);self.assertNotIn('1000001',db.c.queries[0])
            self.assertIn('TOP (3)' if kind == 'sql-server' else 'FETCH FIRST 3' if kind == 'oracle' else 'LIMIT 3',db.c.queries[0])
    def test_invalid_limits_and_selections_never_open_database(self):
        for limit in (0, 51, True, '1'):
            with self.assertRaises(sampling.SampleError): sampling.sample('sql-server',{}, {'source':{},'limit':limit})
        with patch('sql_server_reader.catalogue',return_value=[{'name':'id','type':'integer'}]):
            with self.assertRaises(sampling.SampleError): sampling.sample('sql-server',{'connection':{}},{'source':{},'columns':['id','id']})
    def test_api_stops_before_following_another_page(self):
        emitted=[]
        def scan(settings, table, emit, sample_limit=None):
            self.assertEqual(sample_limit, 2)
            for i in range(1000): emitted.append(i);emit({'id':i})
        with patch('hubspot_reader.catalogue',return_value=[{'name':'id','type':'string'}]),patch('hubspot_reader.scan',side_effect=scan):
            result=sampling.sample('hubspot',{}, {'source':{'object':'contacts'},'limit':2})
        self.assertEqual(result['rows'],[[0],[1]]);self.assertEqual(emitted,[0,1,2]);self.assertTrue(result['truncated'])
    def test_file_preview_and_projection_are_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve()/'orders.csv';path.write_text('id,name\n1,A\n2,B\n3,C\n')
            result=access.execute({'connector':'files','action':'sample','settings':{},'source':{'path':str(path),'format':'csv'},'limit':2,'columns':['name']})
            self.assertEqual(result['sample']['rows'],[['A'],['B']]);self.assertEqual(result['scope'],'data');self.assertTrue(result['sample']['truncated'])
            path.write_text('id\n1\n2\n');result=access.execute({'connector':'files','action':'sample','settings':{},'source':{'path':str(path),'format':'csv'},'columns':['unknown']})
            self.assertEqual(result['status'],'failed');self.assertNotIn('sample',result)
    def test_upstream_exception_payload_is_not_exposed(self):
        with patch.object(sampling,'database_sample',side_effect=ValueError('password and business row')):
            result=access.execute({'connector':'sql-server','action':'sample','settings':{},'source':{}})
        self.assertNotIn('business',json.dumps(result));self.assertNotIn('password',json.dumps(result));self.assertEqual(result['status'],'failed')
    def test_sample_cells_obey_browser_utf16_bound(self):
        self.assertEqual(sampling.cell('😀' * 500), '😀' * 250)

    def test_remote_samples_read_one_file_and_clean_up(self):
        data = b'id,name\n1,A\n2,B\n3,C\n'
        downloaded = []
        def download(*args):
            path = args[-1]; downloaded.append(path); path.write_bytes(data)
        for kind in ('azure-blob','s3','gcs','sftp','sharepoint','onedrive'):
            with patch('azure_blob_reader.download',side_effect=download), \
                 patch('object_store_reader.request',return_value=(data,'etag')) as objects, \
                 patch('sftp_reader.OpenSsh') as ssh, \
                 patch('graph_reader.settings_for',return_value=('user','fixture')), \
                 patch('graph_reader.token',return_value='synthetic'), \
                 patch('graph_reader.drive',return_value=('drive','orders.csv')), \
                 patch('graph_reader.graph',return_value={'file':{},'name':'orders.csv'}), \
                 patch('graph_reader.download',side_effect=download):
                ssh.return_value.list.return_value=[('orders.csv',len(data),False)]
                ssh.return_value.get.side_effect=lambda remote,path:download(Path(path))
                result=sampling.sample(kind,{}, {'source':{'path':'Shared Documents/orders.csv' if kind == 'sharepoint' else 'orders.csv','format':'csv'},'limit':2,'columns':['name']})
                self.assertEqual(result,{'columns':['name'],'rows':[['A'],['B']],'truncated':True})
                if kind in ('s3','gcs'):
                    self.assertEqual(objects.call_count,1)
                    self.assertEqual(objects.call_args.args[3:5],('GET','orders.csv'))
        self.assertTrue(all(not p.exists() for p in downloaded))

    def test_remote_folder_and_oversize_are_rejected_before_download(self):
        for entries in ([('folder',1,True)],[('orders.csv',64*1024*1024+1,False)]):
            with patch('sftp_reader.OpenSsh') as ssh:
                ssh.return_value.list.return_value=entries
                with self.assertRaises(sampling.SampleError):
                    sampling.sample('sftp',{}, {'source':{'path':'orders.csv','format':'csv'}})
                ssh.return_value.get.assert_not_called()
        with patch('graph_reader.settings_for',return_value=('user','fixture')), \
             patch('graph_reader.token',return_value='synthetic'), \
             patch('graph_reader.drive',return_value=('drive','folder')), \
             patch('graph_reader.graph',return_value={'folder':{}}), \
             patch('graph_reader.download') as download:
            with self.assertRaises(sampling.SampleError):
                sampling.sample('onedrive',{}, {'source':{'path':'folder','format':'csv'}})
            download.assert_not_called()

    def test_remote_metadata_keeps_source_identity_and_header_types(self):
        source={'path':'data/orders.csv','format':'csv'}
        with patch('object_store_reader.request',return_value=(b'id,label\nsecret,business-row\n','etag')):
            result=access.execute({'connector':'s3','action':'metadata','settings':{},'tables':[source]})
        self.assertEqual(result['status'],'succeeded')
        entry=result['tables'][0]
        self.assertEqual(entry['source'],source);self.assertEqual(entry['name'],'orders.csv')
        self.assertEqual([c['name'] for c in entry['columns']],['id','label'])
        self.assertNotIn('business-row',json.dumps(result));self.assertNotIn('secret',json.dumps(result))
        with patch('object_store_reader.request') as read:
            result=access.execute({'connector':'s3','action':'metadata','settings':{},'tables':[{'path':'data/orders.json','format':'json'}]})
            self.assertEqual(result['status'],'unsupported');read.assert_not_called()

    def test_empty_file_still_checks_selected_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve()/'empty.csv';path.write_text('id,name\n')
            with self.assertRaises(sampling.SampleError):
                sampling.sample('files',{}, {'source':{'path':str(path),'format':'csv'},'columns':['unknown']})
            self.assertEqual(sampling.sample('files',{}, {'source':{'path':str(path),'format':'csv'},'columns':['name']})['rows'],[])

    def test_sharepoint_list_stops_at_probe_row(self):
        emitted=[]
        def scan(access,locator,table,emit,sample_limit=None):
            self.assertEqual(sample_limit,2)
            for n in range(1000): emitted.append(n);emit({'id':n})
        with patch('graph_reader.list_catalogue',return_value=[{'name':'id','type':'integer'}]), \
             patch('graph_reader.token',return_value='synthetic'), \
             patch('graph_reader.settings_for',return_value=('site','fixture','site')), \
             patch('graph_reader.scan_list',side_effect=scan):
            result=sampling.sample('sharepoint',{}, {'source':{'entity':'list','path':'Lists/Orders'},'limit':2})
        self.assertEqual(result['rows'],[[0],[1]]);self.assertTrue(result['truncated']);self.assertEqual(emitted,[0,1,2])

    def test_github_schema_projection_context_and_probe_bound(self):
        columns=[{'name':n,'type':'string'} for n in ('id','repo','org','repo_id','type','title')]+[{'name':'user','type':'string','supported':False}]
        calls=[]
        def read(host,target,headers):
            calls.append(target)
            return json.dumps({'id':99} if '?' not in target else [{'id':n,'title':'A\x00B',**({'pull_request':{}} if n==2 else {})} for n in (1,2,3)]).encode()
        with patch('source_access.github_metadata',return_value=([{'columns':columns}],None)),patch('source_access.api',side_effect=read):
            result=sampling.sample('github',{'authentication':'anonymous','repositories':['fixture/orders']},{'source':{'stream':'issues'},'limit':2,'columns':['id','repo','org','repo_id','type','title']})
            self.assertEqual(result['rows'],[[1,'orders','fixture',99,'issue','AB'],[2,'orders','fixture',99,'pull_request','AB']])
            self.assertTrue(result['truncated']);self.assertEqual(len(calls),2);self.assertIn('per_page=3',calls[1])
            with self.assertRaises(sampling.SampleError):
                sampling.sample('github',{'repositories':['fixture/orders']},{'source':{'stream':'issues'},'columns':['user']})

    def test_unicode_wide_sample_respects_total_byte_budget(self):
        data={'columns':[str(n) for n in range(100)],'rows':[['界'*500]*100]*50,'truncated':False}
        with patch.object(sampling,'database_sample',return_value=data):
            result=sampling.sample('sql-server',{}, {'source':{},'limit':50})
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False).encode()),500000);self.assertTrue(result['truncated'])
        self.assertLessEqual(len(json.dumps(result).encode()),1000000)
