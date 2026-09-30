"""Stripe reader behaviour against the documented list API (PB-064 phase 4)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mocks'))
import stripe_reader as reader
from stripe_api import StripeApi
import singer_runtime
sys.modules.setdefault('snapshot_runtime', singer_runtime)
# Importing the runtime installs it into the shared workflow; restore afterwards.
_before = (singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review)
import stripe_runtime
singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review = _before

KEY = 'sk_test_' + 'SyntheticKey0123456789'
TABLE = {'object': 'customers', 'columns': ['id', 'balance']}


def customers(n):
    return [{'id': f'cus_{i}', 'object': 'customer', 'balance': i, 'created': i, 'livemode': False}
            for i in range(n)]


class Stripe(unittest.TestCase):
    def setUp(self):
        self.api = StripeApi(KEY)
        self.api.load('customers', customers(250))
        transport = patch.object(reader.http.client, 'HTTPSConnection', self.api.connection())
        transport.start()
        self.addCleanup(transport.stop)

    def test_pages_with_the_documented_cursor(self):
        rows = []
        schema = reader.scan({'api_key': KEY}, TABLE, rows.append)
        self.assertEqual(len(rows), 250)
        self.assertEqual(rows[0], {'id': 'cus_0', 'balance': 0})
        self.assertEqual(schema['properties']['balance'], {'type': ['null', 'integer']})
        targets = [t for _, t in self.api.requests]
        self.assertEqual(targets, ['/v1/customers?limit=100', '/v1/customers?limit=100&starting_after=cus_99',
                                   '/v1/customers?limit=100&starting_after=cus_199'])

    def test_discovery_reads_one_page(self):
        reader.scan({'api_key': KEY}, TABLE)
        self.assertEqual(len(self.api.requests), 1)

    def test_status_codes_map_to_safe_errors(self):
        for status, code in [(401, 'STRIPE_AUTH'), (403, 'STRIPE_FORBIDDEN'), (429, 'STRIPE_RATE_LIMIT'),
                             (503, 'STRIPE_UNAVAILABLE'), (302, 'STRIPE_RESPONSE'), (400, 'STRIPE_RESPONSE')]:
            self.api.fail['customers'] = status
            with self.subTest(status=status), self.assertRaises(reader.StripeError) as error:
                reader.scan({'api_key': KEY}, TABLE)
            self.assertEqual(error.exception.code, code)
            self.assertNotIn(KEY, reader.ERRORS[code])

    def test_wrong_key_is_rejected_without_echo(self):
        with self.assertRaises(reader.StripeError) as error:
            reader.scan({'api_key': 'sk_test_' + 'OtherKey0123456789'}, TABLE)
        self.assertEqual(error.exception.code, 'STRIPE_AUTH')
        self.assertNotIn('OtherKey', str(error.exception))

    def test_field_drift_and_object_mismatch_fail(self):
        self.api.load('customers', [{**customers(1)[0], 'balance': '1'}])
        with self.assertRaises(reader.StripeError):
            reader.scan({'api_key': KEY}, TABLE, lambda row: None)
        self.api.load('customers', [{**customers(1)[0], 'object': 'charge'}])
        with self.assertRaises(reader.StripeError):
            reader.scan({'api_key': KEY}, TABLE)
        self.api.load('customers', [{'id': 'cus_1', 'object': 'customer'}])
        with self.assertRaises(reader.StripeError):
            reader.scan({'api_key': KEY}, TABLE)

    def test_settings_and_catalogue_validation(self):
        for key in ['pk_test_abcdefgh123', 'sk_test_short', 'sk_test_abc$defghij', None]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                reader.api_key({'api_key': key})
        with self.assertRaises(ValueError):
            reader.fields('accounts')

    def test_network_failure_is_generic(self):
        with patch.object(reader.http.client, 'HTTPSConnection', side_effect=OSError(KEY)):
            with self.assertRaises(reader.StripeError) as error:
                reader.scan({'api_key': KEY}, TABLE)
        self.assertEqual(error.exception.code, 'STRIPE_NETWORK')


class Contract(unittest.TestCase):
    def test_contract_types_must_match_the_catalogue(self):
        connector = stripe_runtime.Stripe()
        connector.table({'object': 'charges'}, [{'name': 'amount', 'type': 'BIGINT'}])
        with self.assertRaisesRegex(ValueError, 'type differs'):
            connector.table({'object': 'charges'}, [{'name': 'amount', 'type': 'STRING'}])
        with self.assertRaisesRegex(ValueError, 'documented top-level'):
            connector.table({'object': 'charges'}, [{'name': 'metadata', 'type': 'STRING'}])


if __name__ == '__main__':
    unittest.main()
