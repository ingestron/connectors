"""Source-owned migration approval guards; unit fixtures do not qualify a vendor runtime."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'runtime'))
import singer_runtime as workflow
from singer_bridge import snapshot, digest, CheckpointError

SCHEMA={'type':'object','properties':{'id':{'type':['integer']}},'required':['id'],'additionalProperties':False}

class RuntimeMigration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.old=self.root/'old';self.new=self.root/'new';self.old.mkdir();self.new.mkdir()
        project={'project':'synthetic','environment':'dev','flow':'orders','connection':'pg',
                 'execution':{'mode':'local','ingestion':'incremental'},'executionPackage':'local@0.4.9',
                 'sourcePackage':'postgresql@1.1.5','runtimeAssetSha256':digest('old-assets'),'specificationSha256':digest('old-spec'),
                 'tables':{'orders':{'source':{'stream':'orders','schema':'public','table':'orders','incremental':{'watermark':'id','initial':0,'batchSize':2,'consistency':'ordered-committed-append'}},
                                    'columns':[{'name':'id','type':'BIGINT','required':True}]}}}
        self.before={'connector':'postgresql@1.31.5','sourceId':'retail','tenantId':'synthetic','reviewFile':'review.json','projectLock':project,'sourceSettings':{'connection':{'host':'127.0.0.1','password':{'env':'SYNTHETIC_PASSWORD'}}}}
        self.after=copy.deepcopy(self.before);self.after['projectLock'].update(executionPackage='local@0.4.13',sourcePackage='postgresql@1.1.6',runtimeAssetSha256=digest('new-assets'),specificationSha256=digest('new-spec'))
        self.identities={folder:{'bridgeVersion':'0.4.0','connector':'postgresql@1.31.5','licence':'BSD-3-Clause','sourceId':'retail','tenantId':'synthetic','projectSpecSha256':config['projectLock']['specificationSha256'],'runtimeLockSha256':digest(str(folder))} for folder,config in [(self.old,self.before),(self.new,self.after)]}
        catalog={'streams':[{'tap_stream_id':'orders','stream':'orders','schema':SCHEMA,'metadata':[]}]} 
        self.reviews={}
        for folder,config in [(self.old,self.before),(self.new,self.after)]:
            bundle=workflow.review({'apiVersion':'ingestron.singer-discovery/v1','identity':self.identities[folder],'catalog':copy.deepcopy(catalog)},workflow.project_selection(config['projectLock']))
            bundle['status']='approved';self.reviews[folder]=bundle
            (folder/'review.json').write_text(json.dumps(bundle))
            (folder/'runtime.lock.json').write_text(json.dumps({'files':{'singer_bridge.py':digest(str(folder)),'snapshot_runtime.py':digest(str(folder)),'dbapi_reader.py':digest('same-driver'),'requirements.lock.txt':digest('same-dependencies')}}))
        self.namespace=workflow.checkpoint_namespace(self.before);self.output=self.root/'output'
        contract=workflow.accepted(self.reviews[self.old],self.identities[self.old])
        def messages(bookmarks):
            yield {'type':'SCHEMA','stream':'orders','schema':SCHEMA}
            yield {'type':'RECORD','stream':'orders','record':{'id':1}}
            yield {'type':'STATE','value':{'bookmarks':{'orders':'1'},'hasMore':True}}
        snapshot(self.output,self.namespace,'first',contract,{**self.identities[self.old],'reviewSha256':digest(self.reviews[self.old])},messages,checkpoint={'orders':0})
    def upgrade(self,expected=None):
        with patch.object(workflow,'runtime_identity',side_effect=lambda config,folder:self.identities[folder]), patch.object(workflow,'resolve_secrets',side_effect=AssertionError('Migration resolved credentials')), patch.object(workflow,'tap_output',side_effect=AssertionError('Migration accessed the source')):
            return workflow.checkpoint_upgrade(self.after,self.new,self.before,self.old,self.output,expected)
    def test_only_compatible_reviewed_runtime_changes_preserve_cursor_without_credentials(self):
        self.assertEqual(workflow.checkpoint_upgrade_policy(self.before),workflow.checkpoint_upgrade_policy(self.after))
        preview=self.upgrade();self.assertEqual(preview['head']['bookmarks'],{'orders':'1'});self.assertFalse(preview['applied'])
        applied=self.upgrade(preview['digest']);self.assertTrue(applied['applied'])
        self.assertEqual(self.upgrade(),applied)
    def test_source_selection_credentials_watermark_schema_and_scope_changes_are_refused_first(self):
        changes=[lambda c:c.update(sourceId='other'),lambda c:c.update(tenantId='other'),lambda c:c['projectLock'].update(environment='test'),
                 lambda c:c['projectLock']['tables']['orders']['source'].update(table='other'),
                 lambda c:c['projectLock']['tables']['orders']['source']['incremental'].update(watermark='other'),
                 lambda c:c['projectLock']['tables']['orders']['source']['incremental'].update(initial=1),
                 lambda c:c['projectLock']['tables']['orders']['columns'][0].update(type='STRING'),
                 lambda c:c['sourceSettings']['connection'].update(host='foreign')]
        original=copy.deepcopy(self.after)
        for change in changes:
            self.after=copy.deepcopy(original);change(self.after)
            with self.assertRaisesRegex(ValueError,'Extraction policy changed'):self.upgrade()
        self.assertFalse((self.output/self.namespace/'.migrations').exists())
    def test_draft_review_and_changed_source_driver_or_dependency_locks_are_refused(self):
        bundle=copy.deepcopy(self.reviews[self.new]);bundle['status']='draft';(self.new/'review.json').write_text(json.dumps(bundle))
        with self.assertRaisesRegex(ValueError,'approved'):self.upgrade()
        (self.new/'review.json').write_text(json.dumps(self.reviews[self.new]))
        path=self.new/'runtime.lock.json';original=json.loads(path.read_text())
        for name in ['dbapi_reader.py','requirements.lock.txt']:
            changed=copy.deepcopy(original);changed['files'][name]=digest('changed');path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError,'adapter or dependencies changed'):self.upgrade()
        self.assertFalse((self.output/self.namespace/'.migrations').exists())

if __name__=='__main__':unittest.main()
