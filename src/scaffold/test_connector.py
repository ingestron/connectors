"""Shared snapshot conformance plus the starter's read-only source boundary."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parent / 'conformance'))
from harness import Conformance, singer_runtime
_before = (singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review)
import __MODULE___runtime as runtime
singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review = _before
import source_access

SCHEMA = {'type': 'object', 'properties': {'id': {'type': 'integer'}, 'label': {'type': 'string'}}, 'required': ['id', 'label'], 'additionalProperties': False}


class StarterConformance(Conformance, unittest.TestCase):
    def make_connector(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        return runtime.Starter()

    def settings(self): return {'directory': str(self.root)}
    def tables(self): return {name: {'source': {'path': name + '.jsonl'}, 'columns': [{'name': 'id', 'type': 'BIGINT'}, {'name': 'label', 'type': 'STRING'}]} for name in ('first', 'second')}
    def rows(self, stream): return [{'id': 1, 'label': 'a'}, {'id': 2, 'label': 'b'}]
    def load(self, stream, rows):
        (self.root / (stream + '.jsonl')).write_text(''.join(json.dumps(row)+'\n' for row in rows))
        (self.root / (stream + '.jsonl.schema.json')).write_text(json.dumps(SCHEMA))
    def change_schema(self, stream):
        value = json.loads(json.dumps(SCHEMA)); value['properties']['extra'] = {'type': 'boolean'}
        (self.root / (stream + '.jsonl.schema.json')).write_text(json.dumps(value))
    def break_source(self, stream): (self.root / (stream + '.jsonl')).unlink()
    def secret_values(self): return ['SOURCE_VALUE_MUST_STAY_PRIVATE']

    def access(self, action, **request):
        return source_access.execute({'connector': '__ID__', 'action': action, 'settings': self.settings(), **request})

    def test_metadata_reads_only_declared_sidecar_and_paged_inventory(self):
        (self.root / 'first.jsonl').write_text('SOURCE_VALUE_MUST_STAY_PRIVATE\n')
        result = self.access('metadata', tables=[{'path': 'first.jsonl'}]); self.assertEqual(result['status'], 'succeeded')
        self.assertEqual([c['name'] for c in result['tables'][0]['columns']], ['id', 'label'])
        page = self.access('inventory', limit=1); self.assertEqual(page['tables'][0]['name'], 'first.jsonl')
        second = self.access('inventory', limit=1, cursor=page['nextCursor']); self.assertEqual(second['tables'][0]['name'], 'second.jsonl')
        self.assertNotIn('nextCursor', second)
        self.assertEqual(self.access('test')['scope'], 'connection')

    def test_bounded_samples_keep_large_integers_exact_and_values_out_of_errors(self):
        self.load('first', [{'id': 9007199254740993, 'label': 'x'*600}, {'id': 2, 'label': 'b'}])
        result=self.access('sample', source={'path':'first.jsonl'}, limit=1)
        self.assertEqual(result['sample']['rows'], [['9007199254740993','x'*500]])
        self.assertTrue(result['sample']['truncated'])
        for args in ({'limit':51}, {'limit':True}, {'columns':['missing']}, {'columns':['id','id']}):
            self.assertEqual(self.access('sample', source={'path':'first.jsonl'}, **args)['status'],'failed')
        (self.root/'first.jsonl').write_text('SOURCE_VALUE_MUST_STAY_PRIVATE\n')
        failure=self.access('sample',source={'path':'first.jsonl'});self.assertEqual(failure['status'],'failed');self.assertNotIn('SOURCE_VALUE_MUST_STAY_PRIVATE',json.dumps(failure))

    def test_paths_and_symlinks_cannot_escape_the_connection_directory(self):
        outside=tempfile.TemporaryDirectory();self.addCleanup(outside.cleanup)
        value=Path(outside.name)/'outside.jsonl';value.write_text('{}\n')
        (self.root/'escape.jsonl').symlink_to(value)
        for path in ('../outside.jsonl',str(value),'escape.jsonl'):
            self.assertEqual(self.access('metadata',tables=[{'path':path}])['status'],'failed')
            self.assertEqual(self.access('sample',source={'path':path})['status'],'failed')


if __name__ == '__main__': unittest.main()
