"""Bounded document codec foundation; no provider/runtime workflow opt-in yet."""
import copy
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
from metadata_documents import (COLLECTION_LIMIT, DOCUMENT_LIMIT, document_index,
                                read_documents, MetadataCollectionLimit,
                                MetadataDocumentLimit)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


class MetadataDocumentsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def install(self, files):
        for name, content in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def sample(self):
        index, files = document_index('project', {'orders': encoded({'source': {'stream': 'orders'},
                                               'contract': {'description': 'Synthetic source value'}})})
        self.install(files)
        return index

    def test_hundred_distinct_two_hundred_column_contracts_round_trip_without_truncation(self):
        documents, expected = {}, {}
        for table in range(100):
            name = f'table_{table:03d}'
            properties = [{'name': f'business_{column:03d}', 'physicalName': f'column_{column:03d}',
                           'logicalType': 'string', 'physicalType': 'STRING', 'required': True,
                           'description': f'Māori 日本語 😀 {name} field {column}'}
                          for column in range(200)]
            value = {'source': {'stream': name, 'schema': 'synthetic'},
                     'contract': {'apiVersion': 'v3.1.0', 'kind': 'DataContract', 'id': name,
                                  'name': name, 'schema': [{'name': name, 'properties': properties}]},
                     'columns': [{'name': p['physicalName'], 'target': p['name'], 'type': 'STRING',
                                  'required': True} for p in properties]}
            documents[name], expected[name] = encoded(value), value
        index, files = document_index('project', documents)
        self.assertEqual(len(files), 100)
        self.assertGreater(index['totalBytes'], DOCUMENT_LIMIT)
        self.assertLessEqual(index['totalBytes'], COLLECTION_LIMIT)
        self.assertTrue(all(record['bytes'] < DOCUMENT_LIMIT for record in index['documents'].values()))
        self.install(files)
        observed = dict(read_documents(self.root, index, 'project'))
        self.assertEqual(observed, expected)
        self.assertEqual(sum(len(t['contract']['schema'][0]['properties']) for t in observed.values()), 20_000)
        for name, content in documents.items():
            self.assertEqual(index['documents'][name]['sha256'], hashlib.sha256(content).hexdigest())

    def test_bytes_and_logical_expansion_are_bounded_without_raising_single_file_limit(self):
        content = b'{"padding":"' + b'x' * (DOCUMENT_LIMIT - len(b'{"padding":""}')) + b'"}'
        index, files = document_index('review', {'one': content})
        self.assertEqual(index['totalBytes'], DOCUMENT_LIMIT)
        self.install(files)
        self.assertEqual(len(dict(read_documents(self.root, index, 'review'))['one']['padding']),
                         DOCUMENT_LIMIT - len(b'{"padding":""}'))
        with self.assertRaises(MetadataDocumentLimit):
            document_index('review', {'one': content + b' '})
        with self.assertRaises(MetadataCollectionLimit):
            document_index('review', {f'copy_{i}': content for i in range(4)})
        # Reused file references count repeatedly, bounding logical expansion.
        changed = copy.deepcopy(index)
        changed['documents'] = {f'copy_{i}': next(iter(index['documents'].values())) for i in range(4)}
        changed['totalBytes'] = 4 * DOCUMENT_LIMIT
        with self.assertRaises(MetadataCollectionLimit):
            list(read_documents(self.root, changed, 'review'))

    def test_changed_content_missing_files_and_foreign_kinds_fail_closed(self):
        index = self.sample()
        record = index['documents']['orders']
        path = self.root / record['path']
        original = path.read_bytes()
        path.write_bytes(original.replace(b'Synthetic', b'synthetic'))
        with self.assertRaisesRegex(ValueError, '^Invalid or changed reviewed metadata document$'):
            list(read_documents(self.root, index, 'project'))
        path.write_bytes(original)
        with self.assertRaises(ValueError):
            list(read_documents(self.root, index, 'review'))
        path.unlink()
        with self.assertRaises(ValueError):
            list(read_documents(self.root, index, 'project'))

    def test_index_schema_paths_and_size_claims_are_validated_before_any_file_access(self):
        index = self.sample()
        cases = []
        for path in ['../outside.json', '/tmp/outside.json', 'metadata/project/../outside.json',
                     'metadata/review/' + index['documents']['orders']['sha256'] + '.json']:
            changed = copy.deepcopy(index)
            changed['documents']['orders']['path'] = path
            cases.append(changed)
        for key, value in [('bytes', True), ('bytes', -1), ('sha256', 'z' * 64)]:
            changed = copy.deepcopy(index)
            changed['documents']['orders'][key] = value
            cases.append(changed)
        cases.extend([dict(index, totalBytes=index['totalBytes'] + 1), dict(index, extra='unknown'),
                      dict(index, apiVersion='unknown'), dict(index, documents={})])
        for changed in cases:
            with self.subTest(index=changed), self.assertRaises(ValueError):
                list(read_documents(self.root, changed, 'project'))

    def test_symlink_files_symlink_directories_and_fifo_are_never_followed(self):
        index = self.sample()
        path = self.root / index['documents']['orders']['path']
        original = path.read_bytes()
        outside = self.root / 'outside.json'
        outside.write_bytes(original)
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaises(ValueError):
            list(read_documents(self.root, index, 'project'))
        path.unlink()
        os.mkfifo(path)
        with self.assertRaises(ValueError):
            list(read_documents(self.root, index, 'project'))
        path.unlink()
        path.write_bytes(original)
        directory = path.parent
        moved = self.root / 'moved'
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ValueError):
            list(read_documents(self.root, index, 'project'))

    def test_malformed_duplicate_nonfinite_and_nonobject_json_are_refused_without_values(self):
        for value in [b'{"id":1,"id":2}', b'{"private":"source",bad}', b'{"n":NaN}',
                      b'{"n":Infinity}', b'[]', b'"source"', b'{"value":"\xff"}']:
            with self.subTest(content=value), self.assertRaises(ValueError) as context:
                document_index('selection', {'orders': value})
            self.assertEqual(str(context.exception), 'Invalid or changed reviewed metadata document')
        index, files = document_index('selection', {'orders': b'{"decimal":1.234567890123456789}'})
        self.install(files)
        self.assertEqual(dict(read_documents(self.root, index, 'selection'))['orders']['decimal'],
                         Decimal('1.234567890123456789'))

    def test_late_document_change_requires_complete_consumption_before_commit(self):
        index, files = document_index('review', {'first': b'{"table":"first"}',
                                               'second': b'{"table":"second"}'})
        self.install(files)
        reader = read_documents(self.root, index, 'review')
        self.addCleanup(reader.close)
        self.assertEqual(next(reader), ('first', {'table': 'first'}))
        path = self.root / index['documents']['second']['path']
        path.write_bytes(b'{"table":"changed"}')
        with self.assertRaises(ValueError):
            next(reader)


if __name__ == '__main__':
    unittest.main()
