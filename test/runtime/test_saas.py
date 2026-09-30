"""Salesforce, HubSpot and Jira readers against API mocks (PB-064 phase 7)."""
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mocks'))
import rest_client
import salesforce_reader as sf
import hubspot_reader as hs
import jira_reader as jira
from saas_api import SalesforceApi, HubSpotApi, JiraApi

SECRET = 'client-' + 'secret-value'


class Api(unittest.TestCase):
    def use(self, api):
        self.api = api
        transport = patch.object(rest_client.http.client, 'HTTPSConnection', api.connection())
        transport.start()
        self.addCleanup(transport.stop)

    def code(self, fn, *args):
        with self.assertRaises(rest_client.ApiError) as error:
            fn(*args)
        return error.exception.code


class Salesforce(Api):
    SETTINGS = {'instance_url': 'https://acme.my.salesforce.com', 'client_id': 'cid', 'client_secret': SECRET}
    TABLE = {'object': 'Account', 'columns': ['Id', 'NumberOfEmployees'],
             'kinds': {'Id': 'string', 'NumberOfEmployees': 'integer'}}

    def setUp(self):
        self.use(SalesforceApi('cid', SECRET))
        self.api.load('Account', {'Id': 'id', 'NumberOfEmployees': 'int'},
                      [{'Id': str(i), 'NumberOfEmployees': i} for i in range(5)])

    def test_reads_every_page_with_the_describe_types(self):
        rows = []
        sf.scan(self.SETTINGS, self.TABLE, rows.append)
        self.assertEqual([r['NumberOfEmployees'] for r in rows], [0, 1, 2, 3, 4])
        queries = [t for _, _, t in self.api.requests if 'query' in t]
        self.assertEqual(len(queries), 3)
        self.assertIn('SELECT+Id%2C+NumberOfEmployees+FROM+Account', queries[0])

    def test_failures_are_codes(self):
        self.assertEqual(self.code(sf.scan, {**self.SETTINGS, 'client_secret': 'wrong'}, self.TABLE), 'SF_AUTH')
        self.assertEqual(self.code(sf.scan, self.SETTINGS, {**self.TABLE, 'object': 'Missing'}), 'SF_NOT_FOUND')
        self.assertEqual(self.code(sf.scan, self.SETTINGS, {**self.TABLE, 'kinds': {'Id': 'string',
                                                                                  'NumberOfEmployees': 'string'}}),
                         'SF_SCHEMA')
        self.api.fail['Account'] = 503
        self.assertEqual(self.code(sf.scan, self.SETTINGS, self.TABLE, lambda r: None), 'SF_UNAVAILABLE')
        for message in sf.ERRORS.values():
            self.assertNotIn(SECRET, message)

    def test_instance_url_is_a_salesforce_domain(self):
        for url in ['http://acme.my.salesforce.com', 'https://evil.example', 'https://acme.my.salesforce.com/x']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                sf.settings_for({**self.SETTINGS, 'instance_url': url})

    def test_next_records_url_must_stay_on_the_query_resource(self):
        original = self.api.handle

        def outside(host, method, target, headers, body):
            status, value = original(host, method, target, headers, body)
            if isinstance(value, dict) and 'nextRecordsUrl' in value:
                value['nextRecordsUrl'] = '/services/apexrest/other'
            return status, value
        self.api.handle = outside
        self.assertEqual(self.code(sf.scan, self.SETTINGS, self.TABLE, lambda r: None), 'SF_RESPONSE')


class HubSpot(Api):
    TABLE = {'object': 'deals', 'columns': ['id', 'amount', 'hs_is_closed'],
             'kinds': {'id': 'string', 'amount': 'number', 'hs_is_closed': 'boolean'}}

    def setUp(self):
        self.use(HubSpotApi('pat-token-' + 'value'))
        self.api.load('deals', {'amount': 'number', 'hs_is_closed': 'bool'},
                      [{'id': str(i), 'amount': f'{i}.50', 'hs_is_closed': 'true' if i % 2 else 'false'}
                       for i in range(5)] + [{'id': '9', 'amount': '', 'hs_is_closed': None}])

    def test_converts_text_values_and_follows_after(self):
        rows = []
        hs.scan({'access_token': 'pat-token-value'}, self.TABLE, rows.append)
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[1], {'id': '1', 'amount': Decimal('1.50'), 'hs_is_closed': True})
        self.assertEqual(rows[5], {'id': '9', 'amount': None, 'hs_is_closed': None})
        self.assertIn('properties=amount%2Chs_is_closed', self.api.requests[1][2])

    def test_failures_are_codes(self):
        self.assertEqual(self.code(hs.scan, {'access_token': 'wrong-token'}, self.TABLE), 'HUBSPOT_AUTH')
        self.api.objects['deals']['rows'][0]['amount'] = 'n/a'
        self.assertEqual(self.code(hs.scan, {'access_token': 'pat-token-value'}, self.TABLE, lambda r: None),
                         'HUBSPOT_SCHEMA')
        self.assertEqual(self.code(hs.scan, {'access_token': 'pat-token-value'},
                                   {**self.TABLE, 'columns': ['missing'], 'kinds': {'missing': 'string'}}),
                         'HUBSPOT_SCHEMA')

    def test_repeated_cursor_fails(self):
        original = self.api.handle

        def repeat(host, method, target, headers, body):
            status, value = original(host, method, target, headers, body)
            if isinstance(value, dict) and 'paging' in value:
                value['paging']['next']['after'] = '2'
            return status, value
        self.api.handle = repeat
        self.assertEqual(self.code(hs.scan, {'access_token': 'pat-token-value'}, self.TABLE, lambda r: None),
                         'HUBSPOT_RESPONSE')


class Jira(Api):
    SETTINGS = {'site': 'https://acme.atlassian.net', 'email': 'reader@example.invalid', 'api_token': SECRET}
    TABLE = {'object': 'issues', 'columns': ['key', 'summary', 'labels'],
             'kinds': {'key': 'string', 'summary': 'string', 'labels': 'string'}}

    def setUp(self):
        self.use(JiraApi('reader@example.invalid', SECRET))
        self.api.fields = [{'id': 'summary', 'schema': {'type': 'string'}},
                           {'id': 'labels', 'schema': {'type': 'array'}}]
        self.api.issues = [{'id': str(i), 'key': f'D-{i}', 'fields': {'summary': f's{i}', 'labels': ['a', 'b']}}
                           for i in range(5)]

    def test_default_query_is_bounded_and_lists_become_json(self):
        rows = []
        jira.scan(self.SETTINGS, self.TABLE, rows.append)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0], {'key': 'D-0', 'summary': 's0', 'labels': '["a","b"]'})
        self.assertEqual(self.api.searches[0]['jql'], jira.DEFAULT_JQL)
        self.assertEqual(self.api.searches[0]['fields'], ['summary', 'labels'])

    def test_repeated_page_token_fails_instead_of_looping(self):
        self.api.repeat = True
        self.assertEqual(self.code(jira.scan, self.SETTINGS, self.TABLE, lambda r: None), 'JIRA_RESPONSE')

    def test_unbounded_query_and_credentials_fail_as_codes(self):
        self.assertEqual(self.code(jira.scan, self.SETTINGS, {**self.TABLE, 'jql': 'text ~ x'}, lambda r: None),
                         'JIRA_RESPONSE')
        self.assertEqual(self.code(jira.scan, {**self.SETTINGS, 'api_token': 'wrong'}, self.TABLE), 'JIRA_AUTH')
        for site in ['https://evil.example', 'http://acme.atlassian.net']:
            with self.subTest(site=site), self.assertRaises(ValueError):
                jira.settings_for({**self.SETTINGS, 'site': site})

    def test_fixed_tables_page_by_start_at(self):
        self.api.tables['users'] = ('/rest/api/3/users/search', True,
                                    [{'accountId': str(i), 'displayName': f'U{i}', 'active': True} for i in range(3)])
        rows = []
        jira.scan(self.SETTINGS, {'object': 'users', 'columns': ['accountId', 'active'],
                                  'kinds': {'accountId': 'string', 'active': 'boolean'}}, rows.append)
        self.assertEqual(len(rows), 3)


if __name__ == '__main__':
    unittest.main()
