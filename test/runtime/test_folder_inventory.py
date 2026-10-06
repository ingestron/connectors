"""Folder/list selection, bounded transport, continuation and privacy contracts."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode, quote, unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
import folder_access as access
from sftp_reader import bounded_process, SftpError

SETTINGS = {'tenant_id':'11111111-1111-1111-1111-111111111111',
            'client_id':'22222222-2222-2222-2222-222222222222',
            'client_secret':'synthetic-secret', 'site':'https://contoso.sharepoint.com/sites/finance',
            'user':'reader@example.invalid'}
SSH = {'host':'sftp.example.invalid','user':'reader','port':22,'host_key':'ssh-ed25519 AAAAsynthetic',
       'private_key':'synthetic-unit-test-no-key-material'}
LIST_ID = '33333333-3333-3333-3333-333333333333'


def request(kind='sftp', **values):
    return {'connector':kind,'action':'inventory','settings':SSH if kind=='sftp' else SETTINGS,
            'scope':{'directory':'exports' if kind=='sftp' else 'Shared Documents/retail' if kind=='sharepoint' else 'retail'},
            'limit':2, **values}


def listing(names):
    return 'sftp> cd "exports"\nsftp> ls -lan\n' + ''.join(
        '-rw-r--r-- 1 1001 1001 12 Oct 01 2026 '+name+'\n' for name in names)


class SftpInventory(unittest.TestCase):
    def test_lists_only_pinned_folder_with_sorted_filtered_pages(self):
        with patch('sftp_reader.OpenSsh') as client:
            client.return_value.run.return_value=listing(['products.jsonl','orders.csv','customers.tsv','readme.txt'])
            first=access.execute(request())
            self.assertEqual(first['status'],'succeeded',first)
            self.assertEqual([t['name'] for t in first['tables']],['customers.tsv','orders.csv'])
            second=access.execute(request(cursor=first['nextCursor']))
            self.assertEqual([t['source'] for t in second['tables']],[{'path':'exports/products.jsonl','format':'jsonl'}])
            self.assertNotIn('nextCursor',second)
            client.return_value.run.assert_called_with(['cd "exports"','ls -lan'],output_limit=1000000,timeout=60)
            client.return_value.get.assert_not_called()
            filtered=access.execute(request(query='ORD',scope={'directory':'exports','format':'csv'}))
            self.assertEqual([t['name'] for t in filtered['tables']],['orders.csv'])
            self.assertNotIn('columns',first['tables'][0])

    def test_changed_scope_denied_before_transport_and_changed_listing_denied(self):
        with patch('sftp_reader.OpenSsh') as client:
            client.return_value.run.return_value=listing(['a.csv','b.csv','c.csv'])
            first=access.execute(request());cursor=first['nextCursor'];client.reset_mock()
            for changed in [dict(query='changed'),dict(scope={'directory':'other'}),dict(settings={**SSH,'host':'other.example.invalid'})]:
                result=access.execute(request(cursor=cursor,**changed))
                self.assertEqual(result['code'],'ACCESS_INPUT');client.assert_not_called()
            client.return_value.run.return_value=listing(['a.csv','b.csv','new.csv'])
            result=access.execute(request(cursor=cursor))
            self.assertEqual(result['code'],'ACCESS_CHANGED')
            self.assertEqual(result['tables'],[])

    def test_symlinks_directories_and_unselectable_names_are_not_downloaded(self):
        out=listing(['valid.csv','quote"file.csv','pattern*.csv']) + 'drwxr-xr-x 1 1001 1001 0 Oct 01 2026 folder.csv\nlrwxrwxrwx 1 1001 1001 0 Oct 01 2026 link.csv -> /outside.csv\n'
        with patch('sftp_reader.OpenSsh') as client:
            client.return_value.run.return_value=out
            result=access.execute(request());self.assertEqual(result['code'],'UNSUPPORTED_OBJECT_PATH')
            self.assertEqual([t['name'] for t in result['tables']],['valid.csv'])
            client.return_value.get.assert_not_called()

    def test_bad_inputs_are_denied_before_client_or_credentials(self):
        with patch('sftp_reader.OpenSsh') as client:
            for folder in ['','../outside','exports//nested','exports/','a"\nget secret','*.csv','a?','a[b]','//abs']:
                self.assertEqual(access.execute(request(scope={'directory':folder}))['code'],'ACCESS_INPUT',folder)
            for changed in [dict(limit=True),dict(limit=201),dict(query='x'*129),dict(scope={'directory':'exports','entity':'list'}),dict(cursor='%%%')]:
                self.assertEqual(access.execute(request(**changed))['code'],'ACCESS_INPUT')
            client.assert_not_called()

    def test_root_absolute_folder_and_malformed_responses(self):
        with patch('sftp_reader.OpenSsh') as client:
            client.return_value.run.return_value=listing(['a.csv'])
            result=access.execute(request(scope={'directory':'/'}));self.assertEqual(result['tables'][0]['source']['path'],'/a.csv')
            for out in ['PRIVATE_BODY_VALUE synthetic-secret',listing(['a.csv','a.csv']),listing(['a/b.csv'])]:
                client.return_value.run.return_value=out
                result=access.execute(request());self.assertEqual(result['status'],'failed')
                self.assertNotIn('PRIVATE_BODY_VALUE',json.dumps(result));self.assertNotIn('synthetic-secret',json.dumps(result))

    def test_native_host_key_error_remains_private(self):
        with patch('sftp_reader.OpenSsh',side_effect=SftpError('SFTP_HOST_KEY')):
            result=access.execute(request());self.assertEqual(result['code'],'SFTP_HOST_KEY')
            self.assertNotIn('PRIVATE KEY',json.dumps(result))


class BoundedClient(unittest.TestCase):
    def test_drains_both_pipes_and_retains_exit_status(self):
        with tempfile.TemporaryDirectory() as folder:
            result=bounded_process([sys.executable,'-c','import sys; print("listing"); sys.stderr.write("denied"); sys.exit(4)'],folder,1000,5)
            self.assertEqual(result.returncode,4);self.assertEqual(result.stdout,'listing\n');self.assertEqual(result.stderr,'denied')

    def test_stdout_stderr_limits_timeout_and_utf8_denied(self):
        for script,code in [('import sys; sys.stdout.write("x"*1000000)','SFTP_TOO_LARGE'),
                            ('import sys; sys.stderr.write("x"*1000000)','SFTP_TOO_LARGE'),
                            ('import time; time.sleep(2)','SFTP_NETWORK'),
                            ('import os; os.write(1,b"\\xff")','SFTP_RESPONSE')]:
            with self.subTest(code=code),tempfile.TemporaryDirectory() as folder,self.assertRaises(SftpError) as error:
                bounded_process([sys.executable,'-c',script],folder,1000,0.2 if code=='SFTP_NETWORK' else 5)
            self.assertEqual(error.exception.code,code)


class GraphInventory(unittest.TestCase):
    def graph(self,access_token,target):
        self.calls.append(target)
        path=unquote(urlsplit(target).path)
        if '/sites/contoso.sharepoint.com:' in path:return {'id':'site,id'}
        if path.endswith('/drives'):return {'value':[{'id':'drive-docs','webUrl':'https://contoso.sharepoint.com/sites/finance/Shared%20Documents'}]}
        if '/users/' in path and path.endswith('/drive'):return {'id':'drive-user'}
        if '/root:/' in path:return {'id':'folder-id','folder':{}}
        if path.endswith('/children') or path.endswith('/lists'):return self.page
        raise AssertionError('Unexpected request '+target)

    def setUp(self):
        self.calls=[];self.page={'value':[{'id':'item1','name':'orders.csv','file':{},'size':12},{'id':'item2','name':'folder','folder':{}}]}

    def test_selected_file_paths_one_drive_and_sharepoint_without_downloads(self):
        for kind in ('sharepoint','onedrive'):
            with self.subTest(kind=kind),patch('graph_reader.token',return_value='token'),patch('graph_reader.graph',side_effect=self.graph):
                result=access.execute(request(kind));self.assertEqual(result['status'],'succeeded',result)
                expected='Shared Documents/retail/orders.csv' if kind=='sharepoint' else 'retail/orders.csv'
                self.assertEqual(result['tables'][0]['source'],{'path':expected,'format':'csv'})
                self.assertEqual(len(result['tables']),1)
                self.assertFalse(any('/content' in c or '/items?' in c for c in self.calls))

    def test_root_paths_and_list_ids_are_selectable(self):
        with patch('graph_reader.token',return_value='token'),patch('graph_reader.graph',side_effect=self.graph):
            result=access.execute(request('onedrive',scope={}))
            self.assertEqual(result['tables'][0]['source']['path'],'orders.csv')
            self.assertTrue(any('/root/children?' in c for c in self.calls))
            result=access.execute(request('sharepoint',scope={'directory':'Shared Documents'}))
            self.assertEqual(result['tables'][0]['source']['path'],'Shared Documents/orders.csv')
            self.page={'value':[{'id':LIST_ID,'name':'orders','displayName':'Retail orders','list':{'template':'genericList'}},
                                {'id':'lib','name':'Documents','list':{'template':'documentLibrary'}}]}
            result=access.execute(request('sharepoint',scope={'entity':'list'}))
            self.assertEqual(result['tables'][0]['source'],{'entity':'list','path':'Lists/'+LIST_ID})
            self.assertEqual(result['tables'][0]['name'],'Retail orders')

    def test_paging_empty_filters_and_changed_scope_or_collection_denial(self):
        collection='/v1.0/drives/drive-user/items/folder-id/children'
        self.page['@odata.nextLink']='https://graph.microsoft.com'+collection+'?'+urlencode({'$skiptoken':'opaque+next',' $bad':'ignored'})
        self.page['@odata.nextLink']='https://graph.microsoft.com'+collection+'?'+urlencode({'$skiptoken':'opaque+next','$top':2})
        with patch('graph_reader.token',return_value='token') as token,patch('graph_reader.graph',side_effect=self.graph):
            first=access.execute(request('onedrive',query='products'));self.assertEqual(first['tables'],[]);cursor=first['nextCursor']
            self.page={'value':[{'id':'p','name':'products.tsv','file':{},'size':12}]}
            second=access.execute(request('onedrive',query='products',cursor=cursor))
            self.assertEqual(second['tables'][0]['source']['format'],'tsv')
            self.assertIn('%2B',self.calls[-1])
            token.reset_mock()
            bad=access.execute(request('onedrive',query='changed',cursor=cursor));self.assertEqual(bad['code'],'ACCESS_INPUT');token.assert_not_called()
            scoped=access.identity('onedrive',SETTINGS,{'directory':'retail','format':'all'},'products')
            forged=access.encode_cursor(scoped,'/v1.0/users/other/drive/root/children?$skiptoken=x')
            bad=access.execute(request('onedrive',query='products',cursor=forged));self.assertEqual(bad['code'],'ACCESS_RESPONSE')

    def test_nextlinks_restricted_to_same_host_collection_and_metadata_query(self):
        collection='/v1.0/drives/drive-user/items/folder-id/children'
        invalid=['https://evil.invalid'+collection+'?$skiptoken=x', 'http://graph.microsoft.com'+collection+'?$skiptoken=x',
                 'https://graph.microsoft.com:443'+collection+'?$skiptoken=x','https://graph.microsoft.com/v1.0/me/messages?$skiptoken=x',
                 'https://graph.microsoft.com'+collection+'?$skiptoken=x&$expand=fields',
                 'https://graph.microsoft.com'+collection+'?$skiptoken=x&$skiptoken=y',
                 'https://graph.microsoft.com'+collection+'?$top=2']
        for nxt in invalid:
            self.page={'value':[{'id':'a','name':'orders.csv','file':{},'size':12}],'@odata.nextLink':nxt}
            with patch('graph_reader.token',return_value='token'),patch('graph_reader.graph',side_effect=self.graph):
                result=access.execute(request('onedrive'));self.assertEqual(result['code'],'ACCESS_RESPONSE');self.assertEqual(result['tables'],[])

    def test_bad_scope_and_missing_secret_denied_before_auth(self):
        with patch('graph_reader.token') as token:
            for changed in [dict(scope={'directory':'../x'}),dict(scope={'directory':'a%2Fb'}),dict(scope={'directory':'/abs'}),
                            dict(scope={'entity':'list','directory':'Shared Documents'}),dict(scope={'entity':'list','format':'csv'}),dict(scope={})]:
                result=access.execute(request('sharepoint',**changed));self.assertEqual(result['status'],'failed')
            result=access.execute(request('onedrive',settings={**SETTINGS,'client_secret':{'$secret':{'env':'MISSING_FOLDER_SECRET'}}}))
            self.assertEqual(result['code'],'SECRET_MISSING');token.assert_not_called()

    def test_malformed_pages_duplicate_names_and_overflow_fail_atomically(self):
        invalid=[{'value':{}},{'value':[{'name':'orders.csv','file':{},'size':-1}]},
                 {'value':[{'name':'orders.csv','file':{},'size':12}]*2},
                 {'value':[{'name':str(i)+'.csv','file':{},'size':12} for i in range(3)]}]
        for page in invalid:
            self.page=page
            with patch('graph_reader.token',return_value='token'),patch('graph_reader.graph',side_effect=self.graph):
                result=access.execute(request('onedrive'));self.assertEqual(result['status'],'failed');self.assertEqual(result['tables'],[])

    def test_library_resolution_pages_metadata_and_rejects_cycles_or_other_collections(self):
        collection='/v1.0/sites/site%2Cid/drives'
        first={'value':[{'id':'archive-drive','webUrl':'https://contoso.sharepoint.com/sites/finance/Archive'}],
               '@odata.nextLink':'https://graph.microsoft.com'+collection+'?$skipToken=next'}
        second={'value':[{'id':'drive-docs','webUrl':'https://contoso.sharepoint.com/sites/finance/Shared%20Documents'}]}
        def paged(token,target):
            if unquote(urlsplit(target).path).endswith('/drives'):
                self.calls.append(target)
                return second if '$skipToken=next' in target else first
            return self.graph(token,target)
        with patch('graph_reader.token',return_value='token'),patch('graph_reader.graph',side_effect=paged):
            result=access.execute(request('sharepoint'));self.assertEqual(result['status'],'succeeded',result)
            self.assertTrue(any('$skipToken=next' in c for c in self.calls))
            self.assertEqual(result['tables'][0]['source']['path'],'Shared Documents/retail/orders.csv')
        for invalid in ['https://evil.invalid'+collection+'?$skipToken=x',
                        'https://graph.microsoft.com/v1.0/sites/other/drives?$skipToken=x']:
            first['@odata.nextLink']=invalid
            with patch('graph_reader.token',return_value='token'),patch('graph_reader.graph',side_effect=paged):
                result=access.execute(request('sharepoint'));self.assertEqual(result['code'],'GRAPH_RESPONSE');self.assertEqual(result['tables'],[])
        first['@odata.nextLink']='https://graph.microsoft.com'+collection+'?$skipToken=next'
        second['value']=[];second['@odata.nextLink']='https://graph.microsoft.com'+collection+'?'+urlencode({'$top':200,'$select':'id,name,webUrl'})
        with patch('graph_reader.token',return_value='token'),patch('graph_reader.graph',side_effect=paged):
            result=access.execute(request('sharepoint'));self.assertEqual(result['code'],'GRAPH_RESPONSE');self.assertEqual(result['tables'],[])

    def test_list_search_uses_display_name_and_invalid_native_ids_fail_atomically(self):
        self.page={'value':[{'id':LIST_ID,'name':'internal-orders','displayName':'Retail orders','list':{'template':'genericList'}}]}
        with patch('graph_reader.token',return_value='token'),patch('graph_reader.graph',side_effect=self.graph):
            result=access.execute(request('sharepoint',scope={'entity':'list'},query='RETAIL'))
            self.assertEqual(result['tables'][0]['name'],'Retail orders')
            for identifier in ['-'*36,'a'*36,'333333333-333-3333-3333-333333333333']:
                self.page['value'][0]['id']=identifier
                result=access.execute(request('sharepoint',scope={'entity':'list'},query='not-matching'))
                self.assertEqual(result['code'],'ACCESS_RESPONSE');self.assertEqual(result['tables'],[])

    def test_existing_actions_delegate_without_a_new_download_path(self):
        for action in ('test','metadata','sample'):
            selected=request('sharepoint',action=action)
            with patch.object(access,'source_execute',return_value={'existing':True}) as original:
                self.assertEqual(access.execute(selected),{'existing':True});original.assert_called_once_with(selected)


if __name__ == '__main__':
    unittest.main()
