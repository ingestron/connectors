"""Reviewed runtime identity transitions preserve deltas, cursor and original retries."""
import copy
import fcntl
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
from singer_bridge import (snapshot, digest, checkpoint_binding, preview_checkpoint_migration,
                           apply_checkpoint_migration, CheckpointError, restore_checkpoint)

SCHEMA = {'type':'object','properties':{'id':{'type':['integer']}},'required':['id'],'additionalProperties':False}
CONTRACT = {'orders':{'schema_sha256':digest(SCHEMA),'fields':{'id':{'type':'integer','nullable':False}}}}
INITIAL = {'orders':'0'}
POLICY = digest({'source':'synthetic-orders','watermark':'id','initial':0,'batchSize':2})

class Migration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.old={'projectSpecSha256':digest('old-runtime'),'reviewSha256':digest('old-review')}
        self.new={'projectSpecSha256':digest('new-runtime'),'reviewSha256':digest('new-review')}
        self.calls=[]
        self.first=self.commit('first',[1,2],self.old)
        self.base=self.root/'append'
        self.before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.base/'first').iterdir()}
    def identity(self,source):
        return {'namespace':'append','contract_sha256':digest(CONTRACT),'source':source}
    def messages(self,values):
        def factory(bookmarks):
            self.calls.append(copy.deepcopy(bookmarks))
            yield {'type':'SCHEMA','stream':'orders','schema':SCHEMA}
            for value in values:yield {'type':'RECORD','stream':'orders','record':{'id':value}}
            yield {'type':'STATE','value':{'bookmarks':{'orders':str(values[-1]) if values else bookmarks['orders']},'hasMore':True}}
        return factory
    def commit(self,run,values,source,**kwargs):
        return snapshot(self.root,'append',run,CONTRACT,source,self.messages(values),checkpoint={'orders':0},checkpoint_policy_digest=POLICY,**kwargs)
    def preview(self,**kwargs):
        return preview_checkpoint_migration(self.base,self.identity(self.old),self.identity(self.new),INITIAL,kwargs.get('policy',POLICY))
    def apply(self,expected,**kwargs):
        return apply_checkpoint_migration(self.base,self.identity(self.old),self.identity(self.new),INITIAL,POLICY,expected,**kwargs)
    def assert_original(self):
        self.assertEqual({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.base/'first').iterdir()},self.before)
    def test_review_apply_continuation_and_retry_preserve_original_cursor_and_bytes(self):
        with self.assertRaises(CheckpointError):self.commit('unreviewed',[3],self.new)
        preview=self.preview();self.assertFalse(preview['applied']);self.assertEqual(preview['head']['bookmarks'],{'orders':'2'})
        self.assertFalse((self.base/'.migrations').exists());self.assertEqual(len(self.calls),1)
        result=self.apply(preview['digest']);self.assertTrue(result['applied'])
        self.assertEqual(self.preview(),result);self.assertEqual(self.apply(preview['digest']),result)
        second=self.commit('second',[3,4],self.new)
        self.assertEqual(second['state']['sequence'],2);self.assertEqual(second['state']['parent'],digest(self.first))
        self.assertEqual(self.calls[-1],{'orders':'2'})
        third=self.commit('third',[5],self.new);self.assertEqual(third['state']['sequence'],3);self.assertEqual(self.calls[-1],{'orders':'4'})
        self.assertEqual(self.commit('first',[999],self.old),self.first);self.assertEqual(len(self.calls),3)
        self.assertEqual(self.apply(preview['digest']),result)
        self.assert_original()
    def test_changed_head_requires_new_review_and_never_reads_source(self):
        preview=self.preview();self.commit('second',[3],self.old)
        with self.assertRaises(CheckpointError) as e:self.apply(preview['digest'])
        self.assertEqual(e.exception.code,'CHECKPOINT_MIGRATION_STALE');self.assertFalse((self.base/'.migrations').exists())
        self.assertNotEqual(self.preview()['digest'],preview['digest']);self.assertEqual(len(self.calls),2)
    def test_prepublication_failure_and_acknowledgement_loss_are_recoverable(self):
        preview=self.preview()
        with self.assertRaises(RuntimeError):self.apply(preview['digest'],fail_at='written')
        self.assertFalse(list((self.base/'.migrations').glob('*.json')))
        with self.assertRaises(CheckpointError):self.commit('unreviewed',[3],self.new)
        with self.assertRaises(RuntimeError):self.apply(preview['digest'],fail_at='published')
        self.assertEqual(self.apply(preview['digest'])['digest'],preview['digest'])
        self.commit('second',[3],self.new);self.assertEqual(self.calls[-1],{'orders':'2'});self.assert_original()
    def test_lock_and_foreign_identity_cannot_mutate_or_read_data(self):
        preview=self.preview()
        with (self.base/'.writer.lock').open('r+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):self.preview()
            with self.assertRaises(BlockingIOError):self.apply(preview['digest'])
        foreign={**self.identity(self.new),'namespace':'foreign'}
        with self.assertRaises(CheckpointError):preview_checkpoint_migration(self.base,self.identity(self.old),foreign,INITIAL,POLICY)
        self.assertEqual(len(self.calls),1);self.assert_original()
    def test_tampered_journal_and_committed_output_are_rejected_before_reading(self):
        preview=self.preview();self.apply(preview['digest']);path=self.base/'.migrations'/(preview['digest']+'.json');raw=path.read_bytes()
        document=json.loads(raw);document['head']['bookmarks']['orders']='100';path.write_text(json.dumps(document))
        with self.assertRaises(CheckpointError):self.commit('tampered',[3],self.new)
        path.write_bytes(raw);(self.base/'first/orders.parquet').write_bytes(b'changed output')
        with self.assertRaises(CheckpointError) as e:self.commit('changed_output',[3],self.new)
        self.assertEqual(e.exception.code,'CHECKPOINT_HISTORY');self.assertEqual(len(self.calls),1)
    def test_forked_or_wrong_policy_transition_is_rejected(self):
        preview=self.preview();self.apply(preview['digest']);folder=self.base/'.migrations';document=json.loads(next(folder.glob('*.json')).read_text())
        for patch in [{'policyDigest':digest('foreign-policy')},{'head':{**document['head'],'receiptSha256':digest('foreign-head')}},{'initial':{'orders':'1'}}]:
            candidate={**document,**patch};payload={k:v for k,v in candidate.items() if k!='id'};candidate['id']=digest(payload)
            path=folder/(candidate['id']+'.json');path.write_text(json.dumps(candidate))
            with self.assertRaises(CheckpointError):self.commit('forked',[3],self.new)
            path.unlink()
        self.assertEqual(len(self.calls),1);self.assert_original()
    def test_sequential_reviewed_upgrades_retain_one_contiguous_history(self):
        preview=self.preview();self.apply(preview['digest']);self.commit('second',[3],self.new)
        newer={**self.new,'projectSpecSha256':digest('third-runtime')}
        second_preview=preview_checkpoint_migration(self.base,self.identity(self.new),self.identity(newer),INITIAL,POLICY)
        apply_checkpoint_migration(self.base,self.identity(self.new),self.identity(newer),INITIAL,POLICY,second_preview['digest'])
        result=self.commit('third',[4],newer);self.assertEqual(result['state']['sequence'],3);self.assertEqual(self.calls[-1],{'orders':'3'})
        with self.assertRaises(CheckpointError):self.commit('old_writer',[5],self.new)
        self.assertEqual(len(self.calls),3);self.assert_original()
    def test_symlink_and_missing_history_are_refused_without_creating_journals(self):
        target=self.root/'unowned';target.mkdir();(self.base/'.migrations').symlink_to(target,target_is_directory=True)
        with self.assertRaises(CheckpointError):self.preview()
        self.assertFalse(list(target.iterdir()));(self.base/'.migrations').unlink()
        (self.base/'first/commit.json').unlink()
        with self.assertRaises(CheckpointError):self.preview()
        self.assertEqual(len(self.calls),1)

    def test_all_prior_parquet_bytes_are_verified_before_migration_publication(self):
        self.commit('second',[3],self.old)
        (self.base/'first/orders.parquet').write_bytes(b'changed older output')
        with self.assertRaises(CheckpointError) as e:self.preview()
        self.assertEqual(e.exception.code,'CHECKPOINT_HISTORY')
        self.assertFalse((self.base/'.migrations').exists())
        self.assertEqual(len(self.calls),2)
    def test_failed_postmigration_batch_and_large_cursor_preserve_the_reviewed_head(self):
        preview=self.preview();self.apply(preview['digest'])
        with self.assertRaises(RuntimeError):self.commit('interrupted',[3],self.new,fail_at='files')
        self.commit('second',[9007199254740993],self.new)
        self.assertEqual(self.calls[-1],{'orders':'2'})
        self.assertEqual(self.apply(preview['digest'])['digest'],preview['digest'])
        self.commit('third',[9007199254740994],self.new)
        self.assertEqual(self.calls[-1],{'orders':'9007199254740993'})
        self.assert_original()
    def test_single_rehashed_wrong_policy_or_head_cannot_authorise_a_transition(self):
        preview=self.preview();self.apply(preview['digest']);folder=self.base/'.migrations';original=folder/(preview['digest']+'.json');raw=original.read_bytes();document=json.loads(raw)
        for patch in [{'policyDigest':digest('foreign-policy')},{'head':{**document['head'],'receiptSha256':digest('foreign-head')}},{'initial':{'orders':'1'}}]:
            original.unlink()
            candidate={**document,**patch};candidate['id']=digest({k:v for k,v in candidate.items() if k!='id'})
            path=folder/(candidate['id']+'.json');path.write_text(json.dumps(candidate))
            with self.assertRaises(CheckpointError):self.commit('invalid_transition',[3],self.new)
            path.unlink();original.write_bytes(raw)
        self.assertEqual(len(self.calls),1)
        self.assert_original()

if __name__=='__main__':unittest.main()
