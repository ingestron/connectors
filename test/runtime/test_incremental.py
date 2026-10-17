"""Cursor/output atomicity and parameterised append reads; no vendor sockets."""
import copy
import fcntl
import json
from pathlib import Path
import sys
import tempfile
import unittest
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
from singer_bridge import snapshot, digest, CheckpointError
from dbapi_reader import scan
from quality_rules import QualityFailed

SCHEMA = {'type':'object','properties':{'id':{'type':['integer']}},'required':['id'],'additionalProperties':False}
CONTRACT = {'orders': {'schema_sha256':digest(SCHEMA),'fields':{'id':{'type':'integer','nullable':False}}}}
POLICY = {'watermark':'id','initial':0,'consistency':'ordered-committed-append','batchSize':2}


class Cursor:
    def __init__(self, dialect, records, keys=('id',)):
        self.dialect, self.records, self.keys = dialect, records, keys
        self.queries, self.current, self.done = [], '', False
    def execute(self, sql, parameters=()):
        self.queries.append((sql, parameters));self.current=sql;self.done=False
    def fetchall(self):
        if 'PRIMARY' in self.current or 'all_constraints' in self.current: return [(key,) for key in self.keys]
        return [('id','NUMBER' if self.dialect=='oracle' else 'bigint',19,0,'N' if self.dialect=='oracle' else 'NO')]
    def fetchmany(self, count):
        if self.done:return []
        self.done=True;return [(value,) for value in self.records]
class Database:
    def __init__(self, dialect, records, keys=('id',)):
        self.cursor_value=Cursor(dialect,records,keys);self.closed=False
    def cursor(self):return self.cursor_value
    def close(self):self.closed=True


class Incremental(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source={'lockedProject':'synthetic-reviewed-policy'}
    def messages(self, values, calls, more=False):
        def factory(bookmarks):
            calls.append(copy.deepcopy(bookmarks))
            yield {'type':'SCHEMA','stream':'orders','schema':SCHEMA}
            for value in values:yield {'type':'RECORD','stream':'orders','record':{'id':value}}
            yield {'type':'STATE','value':{'bookmarks':{'orders':str(values[-1]) if values else bookmarks['orders']},'hasMore':more}}
        return factory
    def commit(self, run, values, calls, **kwargs):
        return snapshot(self.root,'append',run,CONTRACT,self.source,self.messages(values,calls,kwargs.pop('more',False)),checkpoint={'orders':0},**kwargs)
    def test_cursor_advances_with_output_and_retry_does_not_read_again(self):
        calls=[];first=self.commit('first',[1,2],calls,more=True)
        self.assertEqual(first['state']['bookmarks'],{'orders':'2'});self.assertTrue(first['state']['hasMore'])
        self.assertEqual(calls,[{'orders':'0'}])
        self.assertEqual(self.commit('first',[99],calls),first);self.assertEqual(len(calls),1)
        second=self.commit('second',[3],calls)
        self.assertEqual(calls[-1],{'orders':'2'});self.assertEqual(second['state']['sequence'],2)
        self.assertEqual(pq.read_table(self.root/'append/second/orders.parquet').to_pylist(),[{'id':3}])
        empty=self.commit('empty',[],calls)
        self.assertEqual(empty['state']['bookmarks'],{'orders':'3'});self.assertEqual(empty['tables'][0]['rows'],0)
    def test_precommit_interruptions_leave_the_previous_cursor(self):
        calls=[];self.commit('first',[1],calls)
        for stage in ('record','files'):
            with self.assertRaises(RuntimeError):self.commit('interrupted_'+stage,[2],calls,fail_at=stage)
            self.assertFalse((self.root/'append'/('interrupted_'+stage)).exists())
        self.commit('recovered',[2],calls)
        self.assertEqual(calls[-1],{'orders':'1'})
        self.assertFalse([p for p in (self.root/'append').iterdir() if p.name.startswith('.attempt-')])
    def test_acknowledgement_loss_reuses_commit_and_next_run_restores_it(self):
        calls=[]
        with self.assertRaises(RuntimeError):self.commit('ack_lost',[1],calls,fail_at='committed')
        recovered=self.commit('ack_lost',[2],calls)
        self.assertEqual(recovered['state']['bookmarks'],{'orders':'1'});self.assertEqual(len(calls),1)
        self.commit('next',[2],calls);self.assertEqual(calls[-1],{'orders':'1'})
    def test_quality_failure_does_not_advance(self):
        calls=[];self.commit('first',[1],calls)
        rule={'schema':[{'name':'orders','properties':[{'name':'id','logicalType':'integer','physicalType':'BIGINT','required':True}],
                         'quality':[{'metric':'rowCount','mustBe':0,'severity':'error'}]}]}
        with self.assertRaises(QualityFailed):self.commit('bad_quality',[2],calls,rules={'orders':rule})
        self.commit('recovered',[2],calls);self.assertEqual(calls[-1],{'orders':'1'})
    def test_history_and_source_changes_are_rejected_before_reading(self):
        calls=[];self.commit('first',[1],calls);self.commit('second',[2],calls)
        self.source['lockedProject']='changed'
        with self.assertRaisesRegex(ValueError,'changed'):self.commit('third',[3],calls)
        self.assertEqual(len(calls),2);self.source['lockedProject']='synthetic-reviewed-policy'
        commit=self.root/'append/first/commit.json';data=json.loads(commit.read_text());data['state']['bookmarks']['orders']='0';commit.write_text(json.dumps(data))
        with self.assertRaises(CheckpointError) as failure:self.commit('third',[3],calls)
        self.assertEqual(failure.exception.code, 'CHECKPOINT_HISTORY')
        self.assertEqual(len(calls),2)
    def test_concurrent_writer_and_cursor_regression_are_rejected(self):
        calls=[];self.commit('first',[2],calls)
        with self.assertRaisesRegex(ValueError,'regressing'):self.commit('regress',[1],calls)
        with (self.root/'append/.writer.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):self.commit('concurrent',[3],calls)
        self.assertEqual(len(calls),2)
    def test_large_cursor_is_exact_text_in_public_receipts(self):
        calls=[];value=9007199254740993
        result=self.commit('large',[value],calls)
        self.assertEqual(json.loads(json.dumps(result))['state']['bookmarks']['orders'],str(value))
        self.commit('next',[value+1],calls);self.assertEqual(calls[-1],{'orders':str(value)})
    def test_database_queries_bind_lower_cursor_and_commit_bounded_batch(self):
        for dialect in ('postgresql','mysql','oracle'):
            db=Database(dialect,[11,12,13]);table={'schema':'sales','table':'orders','columns':['id'],'incremental':POLICY,'lowerCursor':'10'};rows=[]
            scan(dialect,{},table,rows.append,connect=lambda _:db)
            self.assertEqual(rows,[{'id':11},{'id':12}]);self.assertEqual(table['nextCursor'],12);self.assertTrue(table['hasMore']);self.assertTrue(db.closed)
            sql,parameters=db.cursor_value.queries[-1];self.assertEqual(parameters,(10,));self.assertIn('ORDER BY',sql)
            self.assertIn('FETCH FIRST 3 ROWS ONLY' if dialect=='oracle' else 'LIMIT 3',sql)
    def test_nonunique_and_out_of_order_sources_never_advance(self):
        for keys,records in [(('id','other'),[1,2]),(('id',),[2,1]),(('id',),[1,1])]:
            db=Database('postgresql',records,keys);table={'schema':'sales','table':'orders','columns':['id'],'incremental':POLICY}
            with self.assertRaises(ValueError):scan('postgresql',{},table,lambda _:None,connect=lambda _:db)
            self.assertTrue(db.closed);self.assertNotIn('nextCursor',table)


if __name__ == '__main__':unittest.main()
