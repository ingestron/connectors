"""Source-layer opt-in only; compiler/provider and indexed review integration pending."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
from metadata_documents import document_index
import singer_runtime as workflow


class IndexedProjectMetadata(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.tables = {}
        for i in range(100):
            name = f'table_{i:03d}'
            properties = [{'name': f'business_{n:03d}', 'physicalName': f'column_{n:03d}',
                           'logicalType': 'string', 'physicalType': 'STRING', 'required': True,
                           'description': f'Māori 日本語 😀 table {i} field {n}'} for n in range(200)]
            self.tables[name] = {
                'source': {'stream': name, 'path': str(self.root / f'{name}.csv'), 'format': 'csv'},
                'contract': {'apiVersion': 'v3.1.0', 'kind': 'DataContract', 'id': name,
                             'schema': [{'name': name, 'properties': properties}]},
                'columns': [{'name': p['physicalName'], 'target': p['name'],
                             'type': 'STRING', 'required': True} for p in properties]}
        index, files = document_index('project', {name: json.dumps(value, ensure_ascii=False,
                                      separators=(',', ':')).encode() for name, value in self.tables.items()})
        self.project = {'tableDocuments': index}
        for name, content in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def test_complete_selection_and_authored_contracts_equal_legacy_semantics(self):
        legacy = {'tables': self.tables}
        self.assertEqual(workflow.project_tables(self.project, self.root), self.tables)
        selection = workflow.project_selection(self.project, self.root)
        self.assertEqual(selection, workflow.project_selection(legacy))
        self.assertEqual(workflow.project_contracts(self.project, self.root), workflow.project_contracts(legacy))
        self.assertEqual(len(selection), 100)
        self.assertEqual(sum(len(s['fields']) for s in selection.values()), 20_000)
        self.assertEqual(selection['table_099']['fields']['column_199']['target'], 'business_199')

    def test_missing_context_ambiguous_forms_changed_documents_and_wrong_kinds_refuse(self):
        with self.assertRaisesRegex(ValueError, 'owned bundle directory'):
            workflow.project_selection(self.project)
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            workflow.project_tables({**self.project, 'tables': self.tables}, self.root)
        changed = copy.deepcopy(self.project)
        changed['tableDocuments']['kind'] = 'review'
        with self.assertRaises(ValueError):
            workflow.project_contracts(changed, self.root)
        path = self.root / self.project['tableDocuments']['documents']['table_099']['path']
        path.write_bytes(path.read_bytes().replace(b'business_199', b'changed__199'))
        with self.assertRaises(ValueError):
            workflow.project_selection(self.project, self.root)

    def test_discovery_only_document_remains_uncontracted_and_extra_shape_refuses(self):
        for table, valid in [({'source': {'stream': 'orders'}, 'columns': []}, True),
                             ({'source': {'stream': 'orders'}, 'columns': [], 'extra': 'unsupported'}, False),
                             ({'source': {'stream': 'orders'}, 'columns': [], 'contract': {}}, False)]:
            index, files = document_index('project', {'orders': json.dumps(table).encode()})
            for name, content in files.items():
                path = self.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            project = {'tableDocuments': index}
            if valid:
                self.assertEqual(workflow.project_selection(project, self.root), {})
                self.assertEqual(workflow.project_contracts(project, self.root), {})
            else:
                with self.assertRaises(ValueError):
                    workflow.project_tables(project, self.root)


if __name__ == '__main__':
    unittest.main()
