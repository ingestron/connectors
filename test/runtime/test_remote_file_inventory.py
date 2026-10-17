"""Cloud inventory protocol, selection, pagination and privacy invariants."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
import remote_file_access as access
from source_access import AccessError
from object_store_reader import StoreError

SETTINGS = {'bucket': 'synthetic-retail', 'region': 'us-east-1',
            'access_key_id': 'SYNTHETIC-KEY', 'secret_access_key': 'synthetic-secret'}
AZURE = {'account': 'syntheticretail', 'container': 'bronze',
         'sas_token': 'sv=2023-11-03&sp=rl&se=2099-01-01&spr=https&sig=synthetic-secret'}


def store(keys, token=None, namespace='http://s3.amazonaws.com/doc/2006-03-01/', encoded=False):
    body = ''.join('<Contents><Key>' + escape(k) + '</Key><Size>12</Size></Contents>' for k in keys)
    body += '<IsTruncated>' + ('true' if token else 'false') + '</IsTruncated>'
    if token:
        body += '<NextContinuationToken>' + escape(token) + '</NextContinuationToken>'
    if encoded:
        body += '<EncodingType>url</EncodingType>'
    return ('<ListBucketResult xmlns="' + namespace + '">' + body + '</ListBucketResult>').encode()


def azure(keys, token='', directories=()):
    body = ''.join('<Blob><Name>' + escape(k) + '</Name><Properties><Content-Length>12</Content-Length>'
                   + ('<ResourceType>directory</ResourceType>' if k in directories else '')
                   + '</Properties></Blob>' for k in keys)
    return ('<EnumerationResults><Blobs>' + body + '</Blobs><NextMarker>'
            + escape(token) + '</NextMarker></EnumerationResults>').encode()


def request(kind='s3', **args):
    return {'connector': kind, 'action': 'inventory', 'settings': AZURE if kind == 'azure-blob' else SETTINGS,
            'scope': {'prefix': 'retail/'}, 'limit': 3, **args}


class CloudInventory(unittest.TestCase):
    def test_s3_gcs_list_only_bounded_v2_and_selectable_sources(self):
        for kind in ('s3', 'gcs'):
            with self.subTest(kind=kind), patch('object_store_reader.request', return_value=(
                    store(['retail/orders.CSV', 'retail/part/products.parquet', 'retail/readme.txt']), None)) as send:
                result = access.execute(request(kind))
                self.assertEqual(result['status'], 'succeeded', result)
                self.assertEqual([t['source'] for t in result['tables']], [
                    {'path': 'retail/orders.CSV', 'format': 'csv'},
                    {'path': 'retail/part/products.parquet', 'format': 'parquet'}])
                self.assertTrue(all(t['kind'] == 'file' and 'columns' not in t for t in result['tables']))
                self.assertEqual(send.call_args.args[3:5], ('GET', ''))
                self.assertEqual(send.call_args.args[5], {'list-type': '2', 'prefix': 'retail/',
                                 'max-keys': 3, 'encoding-type': 'url'})
                self.assertNotIn('synthetic-secret', json.dumps(result))

    def test_cursor_roundtrip_empty_filtered_page_and_changed_scope_denial(self):
        for kind in ('s3', 'gcs', 'azure-blob'):
            mocked = 'source_access.api' if kind == 'azure-blob' else 'object_store_reader.request'
            body = azure(['retail/not-matching.txt'], 'vendor+token/=') if kind == 'azure-blob' else store(['retail/not-matching.txt'], 'vendor+token/=')
            with self.subTest(kind=kind), patch(mocked, return_value=body if kind == 'azure-blob' else (body, None)) as send:
                first = access.execute(request(kind, query='orders'))
                self.assertEqual(first['tables'], [])
                cursor = first['nextCursor']
                second_body = azure(['retail/orders.csv']) if kind == 'azure-blob' else store(['retail/orders.csv'])
                send.return_value = second_body if kind == 'azure-blob' else (second_body, None)
                second = access.execute(request(kind, query='orders', cursor=cursor))
                self.assertEqual(len(second['tables']), 1, second)
                if kind == 'azure-blob':
                    self.assertEqual(parse_qs(urlsplit(send.call_args.args[1]).query)['marker'], ['vendor+token/='])
                else:
                    self.assertEqual(send.call_args.args[5]['continuation-token'], 'vendor+token/=')
                for changed in [dict(query='products'), dict(scope={'prefix': 'elsewhere/'}),
                                dict(scope={'prefix': 'retail/', 'format': 'json'})]:
                    send.reset_mock()
                    bad = access.execute(request(kind, query='orders', cursor=cursor, **{k:v for k,v in changed.items() if k != 'query'})) if 'query' not in changed else access.execute(request(kind, cursor=cursor, **changed))
                    self.assertEqual(bad['code'], 'ACCESS_INPUT')
                    send.assert_not_called()

    def test_azure_list_sas_scope_and_directory_exclusion(self):
        with patch('source_access.api', return_value=azure(
                ['retail/orders.csv', 'retail/folder.parquet', 'retail/sub/products.jsonl'], directories=['retail/folder.parquet'])) as send:
            result = access.execute(request('azure-blob'))
            self.assertEqual(result['status'], 'succeeded', result)
            self.assertEqual(len(result['tables']), 2)
            self.assertEqual(send.call_args.args[0], 'syntheticretail.blob.core.windows.net')
            query = parse_qs(urlsplit(send.call_args.args[1]).query)
            self.assertEqual(query['comp'], ['list'])
            self.assertEqual(query['maxresults'], ['3'])
            self.assertEqual(send.call_args.args[2]['x-ms-version'], '2023-11-03')
            self.assertNotIn('synthetic-secret', json.dumps(result))
        with patch('source_access.api') as send:
            bad = access.execute(request('azure-blob', settings={**AZURE, 'sas_token': AZURE['sas_token'].replace('sp=rl', 'sp=r')}))
            self.assertEqual(bad['code'], 'ACCESS_FORBIDDEN')
            send.assert_not_called()

    def test_literal_query_format_and_url_encoded_names(self):
        with patch('object_store_reader.request', return_value=(store([
                'retail/a%2Bb%20%26%20c.CSV', 'retail/a%2Bb%20%26%20c.jsonl'], encoded=True), None)):
            result = access.execute(request(query='a+b & c', scope={'prefix': 'retail/', 'format': 'csv'}))
            self.assertEqual(result['tables'][0]['source']['path'], 'retail/a+b & c.CSV')
            self.assertEqual(len(result['tables']), 1)
            self.assertNotIn('columns', result['tables'][0])

    def test_unselectable_paths_are_explicitly_omitted_without_hiding_other_files(self):
        with patch('object_store_reader.request', return_value=(store([
                'retail/../orders.csv', 'retail/good.csv', 'retail/' + 'a'*301 + '.csv']), None)):
            result = access.execute(request())
            self.assertEqual(result['code'], 'UNSUPPORTED_OBJECT_PATH')
            self.assertEqual([t['name'] for t in result['tables']], ['good.csv'])

    def test_invalid_input_denied_before_source_access(self):
        bad = [dict(limit=True), dict(limit=201), dict(query='x'*129), dict(cursor='invalid%'),
               dict(scope={'directory':'/tmp'}), dict(scope={'prefix':'../'}),
               dict(scope={'prefix':'/retail'}), dict(scope={'prefix':'retail//'}),
               dict(scope={'prefix':'retail\n'}), dict(scope={'format':'exe'}), dict(schema='dbo'),
               dict(tables=[]), dict(source={})]
        with patch('object_store_reader.request') as send:
            for changed in bad:
                with self.subTest(changed=changed):
                    self.assertEqual(access.execute(request(**changed))['code'], 'ACCESS_INPUT')
            send.assert_not_called()

    def test_secret_missing_denied_without_transport(self):
        with patch.dict('os.environ', {}, clear=True), patch('object_store_reader.request') as send:
            result = access.execute(request(settings={**SETTINGS, 'secret_access_key':{'$secret':{'env':'MISSING_TEST_KEY'}}}))
            self.assertEqual(result['code'], 'SECRET_MISSING')
            send.assert_not_called()

    def test_malformed_vendor_xml_fails_atomically(self):
        invalid = [b'<ListBucketResult', b'<Error><Message>synthetic-secret</Message></Error>',
                   b'<!DOCTYPE x [<!ENTITY y "synthetic-secret">]><ListBucketResult/>',
                   b'<ListBucketResult xmlns="https://evil.invalid"/>',
                   store(['retail/out.csv']).replace(b'<Size>12</Size>', b'<Size>NaN</Size>'),
                   store(['retail/out.csv']).replace(b'<IsTruncated>false</IsTruncated>', b''),
                   store(['retail/out.csv']).replace(b'<Key>', b'<Key>').replace(b'</Key>', b'</Key><Key>x</Key>'),
                   store(['retail/out.csv', 'retail/out.csv']), store(['other/out.csv']),
                   store(['retail/out%Q0.csv'], encoded=True),
                   store(['retail/out.csv']).replace(b'false', b'true'), b'x'*(access.MAX_BODY+1)]
        for body in invalid:
            with self.subTest(body=body[:80]), patch('object_store_reader.request', return_value=(body, None)):
                result = access.execute(request())
                self.assertEqual(result['status'], 'failed', result)
                self.assertEqual(result['tables'], [])
                self.assertNotIn('nextCursor', result)
                self.assertNotIn('synthetic-secret', json.dumps(result))

    def test_vendor_page_overflow_and_repeated_cursor_are_rejected(self):
        with patch('object_store_reader.request', return_value=(store(['retail/a.csv', 'retail/b.csv']), None)):
            self.assertEqual(access.execute(request(limit=1))['code'], 'ACCESS_RESPONSE')
        with patch('object_store_reader.request', return_value=(store([], 'same-token'), None)):
            first = access.execute(request())
            second = access.execute(request(cursor=first['nextCursor']))
            self.assertEqual(second['code'], 'ACCESS_RESPONSE')

    def test_azure_malformed_and_encoded_names(self):
        with patch('source_access.api', return_value=azure(['retail/a%20b.csv']).replace(b'<Name>', b'<Name Encoded="true">')):
            result = access.execute(request('azure-blob'))
            self.assertEqual(result['tables'][0]['source']['path'], 'retail/a b.csv')
        for body in [b'<Error>secret-value</Error>', b'<EnumerationResults/>',
                     azure(['retail/a.csv']).replace(b'<NextMarker></NextMarker>', b''),
                     azure(['retail/a.csv']).replace(b'<Content-Length>12', b'<Content-Length>-1')]:
            with patch('source_access.api', return_value=body):
                result = access.execute(request('azure-blob'))
                self.assertEqual(result['code'], 'ACCESS_RESPONSE')
                self.assertEqual(result['tables'], [])

    def test_transport_diagnostics_never_include_exception_bodies_or_credentials(self):
        for failure in [StoreError('S3_FORBIDDEN'), RuntimeError('synthetic-secret private-row')]:
            with patch('object_store_reader.request', side_effect=failure):
                result = access.execute(request())
                self.assertEqual(result['status'], 'failed')
                self.assertNotIn('synthetic-secret', json.dumps(result))
                self.assertNotIn('private-row', json.dumps(result))
        with patch('source_access.api', side_effect=AccessError('ACCESS_RATE_LIMIT')):
            self.assertEqual(access.execute(request('azure-blob'))['code'], 'ACCESS_RATE_LIMIT')

    def test_existing_access_actions_delegate_unchanged(self):
        for action in ('test', 'metadata', 'sample'):
            selected = request(action=action)
            with patch.object(access, 'source_execute', return_value={'existing': True}) as delegate:
                self.assertEqual(access.execute(selected), {'existing': True})
                delegate.assert_called_once_with(selected)


if __name__ == '__main__':
    unittest.main()
