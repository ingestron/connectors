"""Compiler project hashes and existing runtime hashes use distinct codecs."""
from pathlib import Path
from decimal import Decimal
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
from singer_bridge import project_specification_digest, canonical, digest, checkpoint_binding
import singer_runtime

NODE = r"""
const {createHash}=require('node:crypto');let input='';process.stdin.setEncoding('utf8');
process.stdin.on('data',c=>input+=c);process.stdin.on('end',()=>{
 const value=JSON.parse(input),ordered=v=>Array.isArray(v)?v.map(ordered):v&&typeof v==='object'
 ?Object.fromEntries(Object.keys(v).sort().map(k=>[k,ordered(v[k])])):v;
 const sha=createHash('sha256').update(JSON.stringify(ordered(value))).digest('hex');
 console.log(JSON.stringify({text:JSON.stringify({...value,specificationSha256:sha}),sha}));
});
"""


def compiled(value):
    result = subprocess.run(['node', '-e', NODE], input=json.dumps(value),
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


class ProjectIdentity(unittest.TestCase):
    def test_compiler_json_matches_unicode_keys_strings_and_number_tokens(self):
        cases = [
            {'description': 'Māori 日本語 😀', 'fields': ['id', 'label']},
            {'nested': {'\ue000': 'BMP', '😀': 'astral', '2': 'second', '10': 'tenth',
                        '0': 'zero', '4294967295': 'not an index', '01': 'text'}},
            {'text': 'quotes" slash/ newline\n tab\t \u2028\u2029', 'empty': {}, 'list': []},
            {'numbers': [1.0, -0.0, 1e-6, 1e-7, 1e20, 1e21, 1e23,
                         9007199254740991, 333333333.3333333]},
            {'nullable': None, 'enabled': True, 'disabled': False, 'surrogate': '\ud800'},
        ]
        for value in cases:
            with self.subTest(value=value):
                result = compiled(value)
                self.assertEqual(project_specification_digest(result['text']), result['sha'])
        self.assertNotEqual(digest(cases[0]), compiled(cases[0])['sha'])

    def test_existing_unicode_receipt_decimal_json_and_checkpoint_hashes_are_unchanged(self):
        value = {'label': 'Māori', 'metadata': {'日本語': Decimal('1.20')}}
        expected = '{"label":"M\\u0101ori","metadata":{"\\u65e5\\u672c\\u8a9e":1.20}}'
        self.assertEqual(canonical(value), expected)
        self.assertEqual(digest(value), hashlib.sha256(expected.encode()).hexdigest())
        self.assertEqual(checkpoint_binding({**value, 'run_id': 'first'}), digest(value))
        self.assertEqual(checkpoint_binding({**value, 'run_id': 'retry'}), digest(value))

    def test_changed_and_malformed_project_locks_fail_closed(self):
        result = compiled({'description': 'Māori', 'threshold': 1e-7})
        changed = json.loads(result['text']); changed['description'] = 'Changed description'
        self.assertNotEqual(project_specification_digest(json.dumps(changed)), result['sha'])
        for value in ['[]', '{', '{}', '{"specificationSha256":"x","threshold":NaN}',
                      '{"specificationSha256":"x","setting":1,"setting":2}']:
            with self.subTest(value=value), self.assertRaises((ValueError, KeyError)):
                project_specification_digest(value)

    def test_runtime_identity_checks_exact_compiler_hash_and_lock_before_source_access(self):
        project = {'runtimeContract': 'ingestron.snapshot/python/v1', 'settings': {},
                   'connector': 'singer:files@23.0.1', 'sourceId': 'synthetic',
                   'tenantId': 'synthetic', 'timeoutSeconds': 10, 'selection': {},
                   'execution': {'mode': 'local'},
                   'metadata': {'description': 'Māori 日本語 😀', 'threshold': 1e-7}}
        result = compiled(project); lock = json.loads(result['text'])
        config = {'apiVersion': 'ingestron.singer/v1', 'mode': 'customer-operated',
                  'connector': 'files@23.0.1', 'sourceId': 'synthetic', 'tenantId': 'synthetic',
                  'timeoutSeconds': 10, 'configEnv': 'SYNTHETIC', 'reviewFile': 'review.json',
                  'sourceSettings': {}, 'projectLock': lock}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, data in [('settings.schema.json', {}), ('selection.json', {}),
                               ('runtime.lock.json', {'connector': 'files@23.0.1', 'files': {}})]:
                (root / name).write_text(json.dumps(data))
            (root / 'requirements.lock.txt').write_text('synthetic unit test')
            path = root / 'project-connection.lock.json'; path.write_text(result['text'])
            with patch.dict(singer_runtime.CONNECTORS, {'files@23.0.1': ('pyarrow', '23.0.1', 'files', 'Apache-2.0')}), \
                 patch('singer_runtime.metadata.version', return_value='23.0.1'), \
                 patch('singer_inventory.inventory', return_value=[]):
                self.assertEqual(singer_runtime.runtime_identity(config, root)['projectSpecSha256'], result['sha'])
                changed = json.loads(result['text']); changed['metadata']['description'] = 'Changed'
                path.write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, 'specification hash mismatch'):
                    singer_runtime.runtime_identity(config, root)
                path.write_bytes(b' ' * 2_000_001)
                with patch('singer_runtime.project_specification_digest', side_effect=AssertionError('Oversized project reached hashing')), self.assertRaises(singer_runtime.MetadataLimit):
                    singer_runtime.runtime_identity(config, root)
                path.write_text(compiled({**project, 'sourceId': 'foreign'})['text'])
                with self.assertRaisesRegex(ValueError, 'specification hash mismatch|Project lock changed'):
                    singer_runtime.runtime_identity(config, root)


    def test_document_limits_count_bytes_and_reserve_approval_space(self):
        from types import SimpleNamespace
        from unittest.mock import mock_open
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'review.json'
            path.write_text(json.dumps({'description': 'Māori 日本語 😀'}))
            self.assertEqual(singer_runtime.load(path)['description'], 'Māori 日本語 😀')
            path.write_bytes(b'x' * 2_000_001)
            with self.assertRaises(singer_runtime.MetadataLimit): singer_runtime.load(path)
            opened = mock_open(read_data=b'x' * 2_000_001)
            with patch.object(Path, 'stat', return_value=SimpleNamespace(st_size=1)), \
                 patch.object(Path, 'open', opened), self.assertRaises(singer_runtime.MetadataLimit):
                singer_runtime.document_text(path)
            opened.return_value.read.assert_called_once_with(2_000_001)
        draft = {'status': 'draft', 'description': ''}
        overhead = len(singer_runtime.canonical(draft).encode()) + 1
        draft['description'] = 'x' * (2_000_000 - overhead - 3)
        self.assertEqual(len(singer_runtime.encoded_document(draft).encode()), 1_999_997)
        approved = dict(draft, status='approved')
        self.assertEqual(len(singer_runtime.encoded_document(approved).encode()), 2_000_000)
        draft['description'] += 'x'
        with self.assertRaises(singer_runtime.MetadataLimit): singer_runtime.encoded_document(draft)


if __name__ == '__main__': unittest.main()
