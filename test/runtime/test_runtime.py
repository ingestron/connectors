import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
from singer_runtime import resolve_secrets, tap_output, review, accepted, source_config, execute
from singer_bridge import snapshot, digest, convert

SCHEMA = {'type':'object','properties':{'id':{'type':'integer'},'amount':{'type':['number','null']}}}
DISCOVERY = {'apiVersion':'ingestron.singer-discovery/v1','identity':{'source':'synthetic'},'catalog':{'streams':[
    {'tap_stream_id':'orders','stream':'orders','schema':SCHEMA,'metadata':[]},
    {'tap_stream_id':'ignored','stream':'ignored','schema':SCHEMA,'metadata':[]}]}}
SELECT = {'orders':{'name':'orders','fields':{'id':{'type':'integer','nullable':False},'amount':{'type':'decimal','precision':20,'scale':2,'nullable':True}}}}

class RuntimeTests(unittest.TestCase):
    def test_reviewed_field_mapping_changes_committed_column(self):
        import pyarrow.parquet as pq
        selected = copy.deepcopy(SELECT)
        selected['orders']['fields']['id']['target'] = 'customer_id'
        bundle = review(DISCOVERY, selected)
        properties = bundle['contracts']['orders']['schema'][0]['properties']
        self.assertIn({'name': 'customer_id', 'physicalName': 'id', 'logicalType': 'integer', 'physicalType': 'BIGINT', 'required': True, 'description': 'Explicit reviewed source projection; no business key inferred.'}, properties)
        bundle['status'] = 'approved'
        accepted(bundle, DISCOVERY['identity'])
        def messages():
            yield {'type':'SCHEMA','stream':'orders','schema':SCHEMA}
            yield {'type':'RECORD','stream':'orders','record':{'id':7,'amount':'1.25'}}
        with tempfile.TemporaryDirectory() as directory:
            snapshot(directory, 'tenant', 'mapped', bundle['projection'], {}, messages)
            table = pq.read_table(Path(directory) / 'tenant' / 'mapped' / 'orders.parquet')
            self.assertEqual(table.column_names, ['customer_id', 'amount'])
            self.assertEqual(table.to_pylist()[0]['customer_id'], 7)
        selected['orders']['fields']['amount']['target'] = 'customer_id'
        with self.assertRaisesRegex(ValueError, 'duplicate target'):
            review(DISCOVERY, selected)

    def test_authored_odcs_metadata_is_preserved_and_projection_checked(self):
        generated = review(DISCOVERY, SELECT)['contracts']
        authored = copy.deepcopy(generated)
        authored['orders']['id'] = 'business-orders'
        authored['orders']['description'] = {'purpose':'Authored business metadata'}
        authored['orders']['schema'][0]['properties'][1]['primaryKey'] = True
        result = review(DISCOVERY, SELECT, authored)
        self.assertEqual(result['contracts'], authored)
        result['status'] = 'approved'
        accepted(result, DISCOVERY['identity'])
        authored['orders']['schema'][0]['properties'][1]['required'] = False
        with self.assertRaises(ValueError): review(DISCOVERY, SELECT, authored)


    def test_project_secrets_resolve_only_at_runtime(self):
        reference = {'password': {'$secret': {'env':'SYNTHETIC_PASSWORD'}}}
        with patch.dict(os.environ, {'SYNTHETIC_PASSWORD':'fixture-value'}):
            self.assertEqual(resolve_secrets(reference), {'password':'fixture-value'})
        self.assertEqual(reference['password']['$secret']['env'], 'SYNTHETIC_PASSWORD')
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError): resolve_secrets(reference)
        with self.assertRaises(ValueError): resolve_secrets({'$secret': {'env':'BAD NAME'}})
        with self.assertRaises(ValueError): resolve_secrets({'$secret': {'vaultUrl':'https://not-a-vault.invalid','name':'test','identityClientId':'0'}})


    def test_review_selection_and_odcs_consistency(self):
        result = review(DISCOVERY, SELECT)
        self.assertEqual(result['status'],'draft')
        self.assertEqual(result['contracts']['orders']['schema'][0]['properties'][0]['physicalType'],'DECIMAL(20,2)')
        self.assertFalse(result['catalog']['streams'][1]['metadata'][0]['metadata']['selected'])
        with self.assertRaises(ValueError): accepted(result, DISCOVERY['identity'])
        result['status']='approved'
        accepted(result,DISCOVERY['identity'])
        result['contracts']['orders']['schema'][0]['properties'][1]['required']=False
        with self.assertRaises(ValueError): accepted(result,DISCOVERY['identity'])

    def test_bad_review_rejected(self):
        for change in [{'type':'date','nullable':False},{'type':'integer'},{'type':'decimal','nullable':False,'precision':39,'scale':2}]:
            selected=copy.deepcopy(SELECT); selected['orders']['fields']['id']=change
            with self.assertRaises((ValueError,KeyError)): review(DISCOVERY,selected)
        selected=copy.deepcopy(SELECT);selected['orders']['fields']['unknown']={'type':'string','nullable':True}
        with self.assertRaises(ValueError): review(DISCOVERY, selected)

    def test_github_public_auth_endpoint_guard(self):
        config={'configEnv':'TEST_TAP_CONFIG','connector':'github@1.29.2'}
        with patch.dict(os.environ,{'TEST_TAP_CONFIG':json.dumps({'auth_token':'synthetic','api_url_base':'https://enterprise.example.invalid'})}):
            with self.assertRaisesRegex(ValueError,'GitHub.com only'): source_config(config)

    def test_scalar_coercion_is_rejected(self):
        for value,field in [(True,{'type':'integer'}),('1',{'type':'integer'}),(1.25,{'type':'decimal','precision':10,'scale':2}),(None,{'type':'string','nullable':False}),(float('inf'),{'type':'number'})]:
            with self.subTest(value=value), self.assertRaises(ValueError): convert(value,field)

    def test_fresh_schema_drift_rejected_before_extraction(self):
        approved=review(DISCOVERY,SELECT);approved['status']='approved'
        changed=copy.deepcopy(DISCOVERY['catalog']);changed['streams'][0]['schema']['properties']['new']={'type':'string'}
        with tempfile.TemporaryDirectory() as directory, \
             patch('singer_runtime.runtime_identity',return_value=DISCOVERY['identity']), \
             patch('singer_runtime.load',return_value=approved), \
             patch('singer_runtime.read_catalog',return_value=changed), \
             patch('singer_runtime.tap_output',side_effect=AssertionError('Extraction should not start')):
            config={'sourceId':'demo','tenantId':'demo','connector':'github@1.29.2','reviewFile':'review.json','timeoutSeconds':10}
            with self.assertRaisesRegex(ValueError,'Source schema changed'):
                execute(config,Path(directory),directory,'run',{})
            self.assertFalse(list(Path(directory).glob('*/run/commit.json')))

    def test_public_github_rejects_unqualified_stream(self):
        discovered=copy.deepcopy(DISCOVERY)
        discovered['identity']['connector']='github@1.29.2'
        with self.assertRaisesRegex(ValueError,'not supported'):
            review(discovered,SELECT)

    def test_snapshot_replay_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path, first=self.make_local(directory)
            second=snapshot(directory,'tenant','run',review(DISCOVERY,SELECT)['projection'],{},lambda:self.fail('source contacted'))
            self.assertEqual(first,second)
            (path/'orders.parquet').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):
                snapshot(directory,'tenant','run',review(DISCOVERY,SELECT)['projection'],{},lambda:self.fail('source contacted'))

    def test_review_projection_and_catalogue_tamper_rejected(self):
        bundle=review(DISCOVERY,copy.deepcopy(SELECT));bundle['status']='approved'
        bundle['projection']['orders']['fields']['amount']['scale']=1
        with self.assertRaises(ValueError): accepted(bundle,DISCOVERY['identity'])

    def executable(self, directory, code):
        path=Path(directory)/'tap'
        path.write_text('#!'+sys.executable+'\n'+code);path.chmod(0o700)
        return path

    def test_nonzero_exit_prevents_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            lines=[{'type':'SCHEMA','stream':'orders','schema':SCHEMA},{'type':'RECORD','stream':'orders','record':{'id':1,'amount':'1.25'}}]
            executable=self.executable(directory, 'import sys,json\nfor value in '+repr(lines)+': print(json.dumps(value), flush=True)\nprint("secret sentinel",file=sys.stderr)\nsys.exit(2)\n')
            def messages():
                for line in tap_output(executable,{'password':'sentinel'}, {},10): yield json.loads(line)
            with self.assertRaisesRegex(ValueError,'Upstream process failed'):
                snapshot(directory,'tenant','run',review(DISCOVERY,SELECT)['projection'],{},messages)
            self.assertFalse((Path(directory)/'tenant/run').exists())

    def test_timeout_kills_hung_process(self):
        with tempfile.TemporaryDirectory() as directory:
            executable=self.executable(directory, 'import time\ntime.sleep(30)\n')
            before=time.monotonic()
            with self.assertRaisesRegex(ValueError,'timeout'): list(tap_output(executable,{}, {},0.1))
            self.assertLess(time.monotonic()-before,3)

    def test_config_permissions_and_ambient_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            executable=self.executable(directory, 'import sys,os,json,stat\np=sys.argv[sys.argv.index("--config")+1]\nassert stat.S_IMODE(os.stat(p).st_mode)==0o600\nassert "SECRET_SENTINEL" not in os.environ\nprint(json.dumps({"ok":True}))\n')
            with patch.dict(os.environ,{'SECRET_SENTINEL':'never inherit'}):
                self.assertEqual(json.loads(next(tap_output(executable,{}, {},10))),{'ok':True})

    def make_local(self,directory):
        def messages():
            yield {'type':'SCHEMA','stream':'orders','schema':SCHEMA}
            yield {'type':'RECORD','stream':'orders','record':{'id':9007199254740993,'amount':'1234567890123456.78'}}
            yield {'type':'STATE','value':{'bookmark':'private'}}
        receipt=snapshot(directory,'tenant','run',review(DISCOVERY,SELECT)['projection'],{},messages)
        return Path(directory)/'tenant/run',receipt

    def test_process_kill_then_local_recovery(self):
        import signal
        with tempfile.TemporaryDirectory() as directory:
            script = """import os,signal
from singer_bridge import snapshot
from test_runtime import SCHEMA,DISCOVERY,SELECT,review

def killed():
    yield {'type':'SCHEMA','stream':'orders','schema':SCHEMA}
    yield {'type':'RECORD','stream':'orders','record':{'id':1,'amount':'1.00'}}
    os.kill(os.getpid(),signal.SIGKILL)
snapshot(os.environ['SYNTHETIC_OUTPUT'],'tenant','run',review(DISCOVERY,SELECT)['projection'],{},killed)
"""
            env={**os.environ,'SYNTHETIC_OUTPUT':directory,'PYTHONPATH':os.pathsep.join([str(Path(__file__).parent),str(Path(__file__).resolve().parents[2]/'runtime')])}
            result=subprocess.run([sys.executable,'-c',script],env=env,capture_output=True)
            self.assertEqual(result.returncode,-signal.SIGKILL)
            self.assertFalse((Path(directory)/'tenant/run/commit.json').exists())
            self.make_local(directory)
            self.assertTrue((Path(directory)/'tenant/run/commit.json').exists())


if __name__ == '__main__': unittest.main()
