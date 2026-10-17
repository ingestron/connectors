"""Consent, exact suggestions, atomic metadata and remote selection privacy."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'runtime'))
import remote_file_schema as access

class RemoteSchema(unittest.TestCase):
    def request(self, kind='sftp', **values):
        return {'connector':kind,'action':'metadata','settings':{},
                'tables':[{'path':'retail/orders.jsonl','format':'jsonl'}],
                'options':{'sampleRecords':True,'limit':2},**values}

    def read(self,kind,settings,source,inspect):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve()/'private-input'
            path.write_text(self.contents.get(source['path'],'{"id":1,"price":12.340,"label":"PRIVATE_RECORD"}\n{"id":2,"price":0.01,"label":null}\n{"id":3,"price":1,"label":"unread"}\n'))
            return inspect({'path':str(path),'format':source['format']})

    def setUp(self):self.contents={}

    def test_all_six_sources_preserve_remote_identity_and_exact_nullable_suggestions(self):
        for kind in access.KINDS:
            with self.subTest(kind=kind),patch('source_sample.remote_file_read',side_effect=self.read):
                result=access.execute(self.request(kind));self.assertEqual(result['status'],'succeeded',result)
                table=result['tables'][0];self.assertEqual(table['source'],self.request(kind)['tables'][0]);self.assertEqual(table['name'],'orders.jsonl')
                fields={f['name']:f for f in table['columns']};self.assertEqual(fields['id']['type'],'integer')
                self.assertEqual((fields['price']['precision'],fields['price']['scale']),(38,3))
                self.assertTrue(all(f['nullable'] and not f.get('key') for f in fields.values()))
                self.assertEqual(table['sampling']['rowCount'],2);self.assertTrue(table['sampling']['truncated'])
                self.assertNotIn('PRIVATE_RECORD',json.dumps(result));self.assertNotIn('private-input',json.dumps(result));self.assertNotIn('rows',json.dumps(result))

    def test_absent_consent_and_invalid_options_never_open_transport(self):
        with patch('source_sample.remote_file_read') as transport:
            for value in [None,{}, {'sampleRecords':False},{'sampleRecords':True,'limit':True},
                          {'sampleRecords':True,'limit':51},{'sampleRecords':True,'secret':'PRIVATE_OPTIONS'}]:
                result=access.execute(self.request(options=value));self.assertEqual(result['status'],'failed');self.assertEqual(result['tables'],[])
                self.assertNotIn('PRIVATE_OPTIONS',json.dumps(result))
            request=self.request();del request['options'];result=access.execute(request)
            self.assertEqual(result['code'],'SAMPLING_REQUIRED');self.assertEqual(result['status'],'unsupported');transport.assert_not_called()
            request=self.request(tables=[{'path':'retail/header.csv','format':'csv'},*request['tables']]);del request['options']
            self.assertEqual(access.execute(request)['code'],'SAMPLING_REQUIRED');transport.assert_not_called()

    def test_later_shape_failure_is_atomic_and_reports_no_record_payload(self):
        self.contents['retail/bad.jsonl']='PRIVATE_BROKEN'
        with patch('source_sample.remote_file_read',side_effect=self.read):
            result=access.execute(self.request(tables=[*self.request()['tables'],{'path':'retail/bad.jsonl','format':'jsonl'}]))
        self.assertEqual(result['status'],'failed');self.assertEqual(result['tables'],[]);self.assertNotIn('PRIVATE_BROKEN',json.dumps(result))

    def test_json_array_nested_fields_and_mixed_header_metadata(self):
        self.contents['retail/array.json']='[{"id":1,"nested":{"name":"PRIVATE_NESTED"}},{"id":2,"nested":{}}]'
        self.contents['retail/header.csv']='id,label\nPRIVATE_NOT_INFERRED,body\n'
        with patch('source_sample.remote_file_read',side_effect=self.read):
            result=access.execute(self.request(tables=[{'path':'retail/header.csv','format':'csv'},{'path':'retail/array.json','format':'json'}]))
        self.assertEqual(result['status'],'succeeded',result);self.assertEqual(result['scope'],'data')
        self.assertTrue(all(c['type']=='string' for c in result['tables'][0]['columns']))
        field=next(c for c in result['tables'][1]['columns'] if c['name']=='nested');self.assertFalse(field['supported']);self.assertEqual(field['sourceType'],'nested-object')
        self.assertNotIn('PRIVATE_',json.dumps(result))

    def test_sharepoint_lists_and_existing_actions_delegate_without_sampling(self):
        with patch('graph_reader.list_catalogue',return_value=[{'name':'id','type':'integer','nullable':False,'key':True}]):
            result=access.execute(self.request('sharepoint',tables=[{'path':'Lists/orders','entity':'list'}]))
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['scope'],'metadata');self.assertNotIn('sampling',result['tables'][0])
        for action in ['test','sample','inventory']:
            request=self.request(action=action)
            with patch.object(access,'original_execute',return_value={'existing':True}) as original:
                self.assertEqual(access.execute(request),{'existing':True});original.assert_called_once_with(request)

if __name__=='__main__':unittest.main()
