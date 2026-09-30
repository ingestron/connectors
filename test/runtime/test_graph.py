"""Microsoft Graph files reader against a Graph mock (PB-064 phase 4)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mocks'))
import graph_reader as reader
from graph_api import GraphApi, TENANT, CLIENT

SECRET = 'graph-client-' + 'secret-value'
SP = {'tenant_id': TENANT, 'client_id': CLIENT, 'client_secret': SECRET,
      'site': 'https://contoso.sharepoint.com/sites/finance'}
OD = {'tenant_id': TENANT, 'client_id': CLIENT, 'client_secret': SECRET, 'user': 'reader@contoso.example'}
TABLE = {'path': 'Shared Documents/retail/a.csv', 'format': 'csv', 'types': {'id': 'integer'}}


class Graph(unittest.TestCase):
    def setUp(self):
        self.api = GraphApi(SECRET)
        self.api.put('drive-docs', 'retail/a.csv', b'id\n1\n2\n')
        self.api.put('drive-user', 'exports/a.csv', b'id\n3\n')
        transport = patch.object(reader.http.client, 'HTTPSConnection', self.api.connection())
        transport.start()
        self.addCleanup(transport.stop)

    def read(self, settings, kind, table):
        rows = []
        schema = reader.scan(settings, kind, table, rows.append)
        return schema, rows

    def code(self, settings, kind, table):
        with self.assertRaises(reader.GraphError) as error:
            self.read(settings, kind, table)
        return error.exception.code

    def test_sharepoint_and_onedrive_files(self):
        schema, rows = self.read(SP, 'sharepoint', TABLE)
        self.assertEqual(rows, [{'id': 1}, {'id': 2}])
        self.assertEqual(schema['properties']['id'], {'type': ['null', 'integer']})
        _, rows = self.read(OD, 'onedrive', {**TABLE, 'path': 'exports/a.csv'})
        self.assertEqual(rows, [{'id': 3}])
        hosts = {h for h, _, _ in self.api.requests}
        self.assertEqual(hosts, {'login.microsoftonline.com', 'graph.microsoft.com', 'contoso.sharepoint.com'})

    def test_failures_map_to_safe_codes(self):
        self.assertEqual(self.code({**SP, 'client_secret': 'wrong'}, 'sharepoint', TABLE), 'GRAPH_AUTH')
        self.assertEqual(self.code(SP, 'sharepoint', {**TABLE, 'path': 'Other Library/a.csv'}), 'GRAPH_NOT_FOUND')
        self.assertEqual(self.code(SP, 'sharepoint', {**TABLE, 'path': 'Shared Documents/missing.csv'}),
                         'GRAPH_NOT_FOUND')
        self.api.truncate.add('retail/a.csv')
        self.assertEqual(self.code(SP, 'sharepoint', TABLE), 'GRAPH_CHANGED')
        self.api.truncate.clear()
        for status, code in [(403, 'GRAPH_FORBIDDEN'), (429, 'GRAPH_RATE_LIMIT'), (503, 'GRAPH_UNAVAILABLE')]:
            self.api.fail['retail/a.csv'] = status
            self.assertEqual(self.code(SP, 'sharepoint', TABLE), code)
        for message in reader.ERRORS.values():
            self.assertNotIn(SECRET, message)

    def test_folders_read_matching_files_and_require_one_schema(self):
        self.api.put('drive-docs', 'retail/orders/b.csv', b'id\n2\n')
        self.api.put('drive-docs', 'retail/orders/a.csv', b'id\n1\n')
        self.api.put('drive-docs', 'retail/orders/c.json', b'[]')
        _, rows = self.read(SP, 'sharepoint', {**TABLE, 'path': 'Shared Documents/retail/orders'})
        self.assertEqual(rows, [{'id': 1}, {'id': 2}])
        self.assertEqual(self.code(SP, 'sharepoint', {**TABLE, 'path': 'Shared Documents/retail/orders',
                                                       'format': 'parquet'}), 'GRAPH_NO_FILES')
        self.api.put('drive-docs', 'retail/orders/d.csv', b'id,extra\n4,x\n')
        with self.assertRaises((reader.GraphError, ValueError)):
            self.read(SP, 'sharepoint', {**TABLE, 'path': 'Shared Documents/retail/orders'})

    def test_downloads_stay_on_the_tenant_host_and_pages_are_followed(self):
        item = {'size': 1, '@microsoft.graph.downloadUrl': 'https://evil.example/file'}
        with self.assertRaises(reader.GraphError):
            reader.download(item, Path('/nonexistent'))
        original = self.api._item

        def outside(drive, path):
            value = original(drive, path)
            if value and 'folder' in value:
                self.api.page_size = 1
            return value
        self.api._item = outside
        self.api.put('drive-docs', 'retail/orders/a.csv', b'id\n1\n')
        self.api.put('drive-docs', 'retail/orders/b.csv', b'id\n2\n')
        _, rows = self.read(SP, 'sharepoint', {**TABLE, 'path': 'Shared Documents/retail/orders'})
        self.assertEqual(len(rows), 2)

    def test_sharepoint_lists_read_contract_fields_across_pages(self):
        self.api.lists['Budgets'] = {'columns': ['Title', 'Amount', 'Approved', 'Owner'],
                                     'items': [{'Title': 'A', 'Amount': 12.5, 'Approved': True},
                                               {'Title': 'B', 'Amount': 3, 'Approved': False,
                                                'Owner': {'Email': 'x@example.invalid'}},
                                               {'Title': 'C'}]}
        table = {'path': 'Lists/Budgets', 'entity': 'list',
                 'types': {'Title': 'string', 'Amount': 'decimal', 'Approved': 'boolean', 'Owner': 'string'}}
        schema, rows = self.read(SP, 'sharepoint', table)
        self.assertEqual(schema['properties']['Amount'], {'type': ['null', 'number']})
        self.assertEqual([r['Title'] for r in rows], ['A', 'B', 'C'])
        self.assertEqual(str(rows[0]['Amount']), '12.5')
        self.assertEqual(rows[1]['Owner'], '{"Email":"x@example.invalid"}')
        self.assertIsNone(rows[2]['Amount'])
        self.assertEqual(self.code(SP, 'sharepoint', {**table, 'types': {'Missing': 'string'}}), 'GRAPH_SCHEMA')
        self.api.lists['Budgets']['items'][0]['Approved'] = 'yes'
        self.assertEqual(self.code(SP, 'sharepoint', table), 'GRAPH_SCHEMA')
        self.assertEqual(self.code(SP, 'sharepoint', {**table, 'path': 'Lists/Other'}), 'GRAPH_NOT_FOUND')

    def test_settings_validation(self):
        for bad in [{**SP, 'tenant_id': 'contoso'}, {**SP, 'site': 'https://evil.example/sites/x'},
                    {**SP, 'site': 'http://contoso.sharepoint.com/sites/finance'}]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                reader.settings_for(bad, 'sharepoint')
        with self.assertRaises(ValueError):
            reader.settings_for({**OD, 'user': 'not a user'}, 'onedrive')
        for path in ['/abs', 'a//b', '../x', 'a/', 'no-library']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                reader.table_path(path, 'sharepoint')

    def test_network_failure_is_generic(self):
        with patch.object(reader.http.client, 'HTTPSConnection', side_effect=OSError(SECRET)):
            self.assertEqual(self.code(SP, 'sharepoint', TABLE), 'GRAPH_NETWORK')


if __name__ == '__main__':
    unittest.main()
