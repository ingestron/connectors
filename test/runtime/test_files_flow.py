from pathlib import Path
import json
import sys
import tempfile
import unittest
from decimal import Decimal, InvalidOperation

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
import singer_runtime
original_runtime = (singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review)
sys.modules['snapshot_runtime'] = singer_runtime
import files_table_runtime as runtime
singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review = original_runtime


class FileFlow(unittest.TestCase):
    def test_two_files_share_one_connection_and_contracts_set_parser_types(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'customers.csv').write_text('id,name\n1,Ada\n')
            (root / 'orders.csv').write_text('amount\n12.50\n')
            config = {'sourceSettings': {}, 'projectLock': {'tables': {
                'customers': {
                    'source': {'path': str(root / 'customers.csv'), 'format': 'csv', 'stream': 'customers'},
                    'columns': [{'name': 'id', 'type': 'BIGINT'}, {'name': 'name', 'type': 'STRING'}]},
                'orders': {
                    'source': {'path': str(root / 'orders.csv'), 'format': 'csv', 'stream': 'orders'},
                    'columns': [{'name': 'amount', 'type': 'DECIMAL(10,2)'}]},
            }}}
            source = runtime.source_config(config)
            self.assertEqual(source['files']['customers']['types'], {'id': 'integer', 'name': 'string'})
            self.assertEqual(source['files']['orders']['types'], {'amount': 'decimal'})
            catalog = json.loads(b''.join(runtime.file_output(None, source, None, 10, True)))
            self.assertEqual([s['tap_stream_id'] for s in catalog['streams']], ['customers', 'orders'])
            for stream in catalog['streams']:
                stream['metadata'] = [{'breadcrumb': [], 'metadata': {'selected': True}}]
            lines = [json.loads(line, parse_float=Decimal) for line in
                     b''.join(runtime.file_output(None, source, catalog, 10)).splitlines()]
            self.assertEqual([line['stream'] for line in lines],
                             ['customers', 'orders', 'customers', 'orders'])
            self.assertEqual(lines[2]['record']['id'], 1)
            self.assertEqual(lines[3]['record']['amount'], Decimal('12.50'))
            (root / 'orders.csv').write_text('amount\ninvalid\n')
            with self.assertRaises(InvalidOperation):
                next(runtime.file_output(None, source, catalog, 10))
            with self.assertRaisesRegex(ValueError, 'Review every table'):
                runtime.file_review({'catalog': catalog}, {'customers': {}})
            config['projectLock']['tables']['orders']['source']['types'] = {'amount': 'string'}
            with self.assertRaisesRegex(ValueError, 'stream identity'):
                runtime.source_config(config)

    def test_unsupported_contract_type_is_rejected_before_file_access(self):
        config = {'sourceSettings': {}, 'projectLock': {'tables': {'dates': {
            'source': {'path': '/does-not-exist.csv', 'format': 'csv', 'stream': 'dates'},
            'columns': [{'name': 'date', 'type': 'DATE'}],
        }}}}
        with self.assertRaisesRegex(ValueError, 'contracted column type'):
            runtime.source_config(config)


if __name__ == '__main__': unittest.main()
