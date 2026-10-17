import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
import files_access as access


class FilesInventory(unittest.TestCase):
    def request(self, folder, **options):
        return {'connector': 'files', 'action': 'inventory', 'settings': {},
                'scope': {'directory': str(folder)}, **options}

    def test_sorted_keyset_pages_and_formats_never_open_records(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory).resolve()
            for name in ('z.parquet', 'a.csv', 'b.tsv', 'c.json', 'd.JSONL', 'ignore.txt'):
                (folder / name).write_text('PRIVATE_RECORD_BROKEN_DATA')
            (folder / 'link.csv').symlink_to(folder / 'a.csv')
            (folder / 'nested.csv').mkdir()
            with patch.object(Path, 'open', side_effect=AssertionError('No data reads')):
                first = access.execute(self.request(folder, limit=2))
                self.assertEqual(first['status'], 'succeeded', first)
                self.assertEqual([t['name'] for t in first['tables']], ['a.csv', 'b.tsv'])
                second = access.execute(self.request(folder, limit=2, cursor=first['nextCursor']))
                third = access.execute(self.request(folder, limit=2, cursor=second['nextCursor']))
            self.assertEqual([t['name'] for t in second['tables']], ['c.json', 'd.JSONL'])
            self.assertEqual([t['name'] for t in third['tables']], ['z.parquet'])
            self.assertNotIn('nextCursor', third)
            self.assertEqual(second['tables'][1]['source'], {'path': str(folder / 'd.JSONL'), 'format': 'jsonl'})
            self.assertNotIn('PRIVATE_RECORD', json.dumps([first, second, third]))

    def test_literal_search_format_filter_and_cursor_scope_fence(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory).resolve()
            for name in ('a.csv', 'b.csv', 'literal%.csv', 'other.tsv'):
                (folder / name).write_text('')
            first = access.execute(self.request(folder, limit=1))
            for options in ({'query': 'a'}, {'scope': {'directory': str(folder), 'format': 'csv'}}):
                result = access.execute(self.request(folder, cursor=first['nextCursor'], **options))
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['code'], 'ACCESS_INPUT')
            result = access.execute(self.request(folder, query='%'))
            self.assertEqual([t['name'] for t in result['tables']], ['literal%.csv'])
            result = access.execute(self.request(folder, scope={'directory': str(folder), 'format': 'tsv'}))
            self.assertEqual([t['name'] for t in result['tables']], ['other.tsv'])
            (folder / 'linked').symlink_to(folder, target_is_directory=True)
            result = access.execute(self.request(folder / 'linked', cursor=first['nextCursor']))
            self.assertEqual(result['status'], 'failed')

    def test_bad_scope_bounds_and_errors_are_private(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory).resolve()
            for options in ({'scope': {}}, {'scope': {'directory': 'relative'}},
                            {'scope': {'directory': str(folder / '..')}}, {'limit': True},
                            {'limit': 201}, {'query': 'x' * 129}, {'schema': 'unexpected'},
                            {'cursor': '{PRIVATE_VALUE'},
                            {'scope': {'directory': str(folder), 'password': 'PRIVATE_VALUE'}}):
                result = access.execute(self.request(folder, **options))
                self.assertEqual(result['status'], 'failed', options)
                self.assertEqual(result['tables'], [])
                self.assertNotIn('PRIVATE_VALUE', json.dumps(result))
            with patch.object(access, 'MAX_ENTRIES', 2):
                for i in range(3):
                    (folder / f'{i}.csv').write_text('')
                result = access.execute(self.request(folder))
                self.assertEqual(result['code'], 'ACCESS_TOO_LARGE')

    def test_listing_needs_no_read_permission_on_ancestor_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory).resolve()
            (folder / 'only.csv').write_text('')
            open_file = os.open
            def reviewed_open(path, flags, *args, **kwargs):
                if Path(path) != folder or kwargs.get('dir_fd') is not None:
                    raise PermissionError('PRIVATE_PERMISSION_TEXT')
                return open_file(path, flags, *args, **kwargs)
            with patch.object(access.os, 'open', side_effect=reviewed_open):
                result = access.execute(self.request(folder))
                self.assertEqual(result['status'], 'succeeded', result)
            with patch.object(access.os, 'open', side_effect=PermissionError('PRIVATE_PERMISSION_TEXT')):
                result = access.execute(self.request(folder))
                self.assertEqual(result['code'], 'ACCESS_FORBIDDEN')
                self.assertNotIn('PRIVATE_PERMISSION_TEXT', json.dumps(result))

    def test_directory_mutation_is_rejected_and_json_metadata_stays_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory).resolve()
            (folder / 'a.csv').write_text('id,name\nPRIVATE_RECORD\n')
            scan = os.scandir
            class MutatingEntries:
                def __enter__(self):
                    self.entries = scan(folder)
                    (folder / 'b.csv').write_text('')
                    return self.entries
                def __exit__(self, *args):
                    self.entries.close()
            with patch.object(access.os, 'scandir', return_value=MutatingEntries()):
                result = access.execute(self.request(folder))
                self.assertEqual(result['code'], 'ACCESS_CHANGED')
            source = {'path': str(folder / 'a.csv'), 'format': 'csv'}
            result = access.execute({'connector': 'files', 'action': 'metadata', 'settings': {}, 'tables': [source]})
            self.assertEqual(result['status'], 'succeeded', result)
            self.assertNotIn('PRIVATE_RECORD', json.dumps(result))
            (folder / 'data.json').write_text('[{"PRIVATE_RECORD": 1}]')
            result = access.execute({'connector': 'files', 'action': 'metadata', 'settings': {},
                                     'tables': [{'path': str(folder / 'data.json'), 'format': 'json'}]})
            self.assertEqual(result['code'], 'SAMPLING_REQUIRED')


if __name__ == '__main__':
    unittest.main()
