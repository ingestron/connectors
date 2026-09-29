import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
from singer_bridge import snapshot
from quality_rules import QualityFailed, contract_rules
from test_runtime import SCHEMA, DISCOVERY, SELECT, review


def contract(key=True, rules=None, amount_rules=None):
    authored = copy.deepcopy(review(DISCOVERY, SELECT)['contracts'])
    table = authored['orders']['schema'][0]
    by_name = {p['name']: p for p in table['properties']}
    if key: by_name['id']['primaryKey'] = True
    if amount_rules: by_name['amount']['quality'] = amount_rules
    if rules: table['quality'] = rules
    return authored


def run(directory, authored, rows, run_id='run'):
    bundle = review(DISCOVERY, SELECT, authored)
    def messages():
        yield {'type': 'SCHEMA', 'stream': 'orders', 'schema': SCHEMA}
        for row in rows:
            yield {'type': 'RECORD', 'stream': 'orders', 'record': row}
    return snapshot(directory, 'tenant', run_id, bundle['projection'], {}, messages,
                    rules={'orders': bundle['contracts']['orders']})


class QualityTests(unittest.TestCase):
    def test_rule_identities_match_core(self):
        ids = {r['id']: r for r in contract_rules(contract(rules=[{'metric': 'rowCount', 'mustBeGreaterThan': 0}])['orders'])}
        self.assertEqual(set(ids), {'orders.rowCount', 'orders.id.key-not-null', 'orders.key-unique'})
        self.assertEqual(ids['orders.rowCount']['outcome'], 'warn')
        self.assertEqual(ids['orders.key-unique']['arguments'], {'properties': ['id']})

    def test_duplicate_key_fails_without_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(QualityFailed) as failure:
                run(directory, contract(), [{'id': 1, 'amount': '1.00'}, {'id': 1, 'amount': '2.00'}])
            [result] = failure.exception.results
            self.assertEqual((result['id'], result['value']), ('orders.key-unique', 1))
            self.assertNotIn('amount', json.dumps(failure.exception.results))
            self.assertFalse((Path(directory) / 'tenant' / 'run').exists())
            self.assertEqual([p.name for p in (Path(directory) / 'tenant').iterdir()], ['.writer.lock'])

    def test_warning_commits_and_is_recorded(self):
        warn = [{'id': 'amount-present', 'metric': 'nullValues', 'mustBe': 0, 'severity': 'warning'}]
        with tempfile.TemporaryDirectory() as directory:
            receipt = run(directory, contract(amount_rules=warn), [{'id': 1, 'amount': None}, {'id': 2, 'amount': '3.00'}])
            quality = {r['id']: r for r in receipt['quality']}
            self.assertEqual(quality['amount-present'], {'stream': 'orders', 'id': 'amount-present', 'metric': 'nullValues',
                                                         'outcome': 'warn', 'source': 'contract', 'value': 1, 'passed': False})
            self.assertTrue(quality['orders.key-unique']['passed'])
            committed = json.loads((Path(directory) / 'tenant' / 'run' / 'commit.json').read_text())
            self.assertEqual(committed['quality'], receipt['quality'])

    def test_library_metrics_and_operators(self):
        rules = [{'id': 'valid', 'metric': 'invalidValues', 'arguments': {'validValues': [1, 2]}, 'mustBeLessOrEqualTo': 1, 'severity': 'error'},
                 {'id': 'pattern', 'metric': 'invalidValues', 'arguments': {'pattern': '[0-9]+'}, 'mustBe': 0},
                 {'id': 'missing', 'metric': 'missingValues', 'mustBeBetween': [0, 50], 'unit': 'percent'},
                 {'id': 'dupes', 'metric': 'duplicateValues', 'mustNotBe': 0}]
        amount = [{'id': 'rows', 'metric': 'rowCount', 'mustBe': 3}]
        with tempfile.TemporaryDirectory() as directory:
            receipt = run(directory, contract(key=False), [{'id': 1}, {'id': 2}, {'id': 3}], 'plain')
            self.assertNotIn('quality', receipt)
            authored = contract(key=False)
            properties = authored['orders']['schema'][0]['properties']
            next(p for p in properties if p['name'] == 'id')['quality'] = rules
            authored['orders']['quality'] = amount
            receipt = run(directory, authored, [{'id': 1}, {'id': 2}, {'id': 2}], 'metrics')
            values = {r['id']: (r['value'], r['passed']) for r in receipt['quality']}
            self.assertEqual(values, {'valid': (0, True), 'pattern': (0, True), 'missing': (0, True),
                                      'dupes': (1, True), 'rows': (3, True)})

    def test_unsupported_library_metric_rejected(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, 'metric'):
            run(directory, contract(amount_rules=[{'metric': 'freshness', 'mustBe': 0}]), [{'id': 1}])


if __name__ == '__main__':
    unittest.main()
