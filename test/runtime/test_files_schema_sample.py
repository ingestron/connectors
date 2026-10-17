import json
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
import files_access as access
import files_schema_sample as sample


class FilesSchemaSample(unittest.TestCase):
    def fixture(self, text, fmt='jsonl'):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name).resolve() / ('records.' + fmt)
        path.write_text(text)
        return path, {'path': str(path), 'format': fmt}

    def request(self, source, **values):
        return {'connector': 'files', 'action': 'metadata', 'settings': {},
                'tables': [source], 'options': {'sampleRecords': True, 'limit': 2}, **values}

    def test_explicit_opt_in_and_invalid_options_open_no_records(self):
        _, source = self.fixture('{"id":1}\n')
        for options in (None, {}, {'sampleRecords': False}, {'sampleRecords': True, 'limit': True},
                        {'sampleRecords': True, 'limit': 51}, {'sampleRecords': True, 'secret': 'PRIVATE_OPTIONS'}):
            with patch.object(sample.os, 'open', side_effect=AssertionError('must not read')):
                result = access.execute(self.request(source, options=options))
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['tables'], [])
            self.assertNotIn('PRIVATE_OPTIONS', json.dumps(result))
        request = self.request(source)
        del request['options']
        result = access.execute(request)
        self.assertEqual(result['code'], 'SAMPLING_REQUIRED')

    def test_exact_int64_decimal_optional_fields_and_no_record_payload(self):
        _, source = self.fixture('[{"id":9223372036854775807,"price":12.340,"name":"PRIVATE_😀","active":true},'
                                 '{"id":2,"price":0.01,"name":null,"active":false},'
                                 '{"id":3,"price":999,"name":"unread","active":true}]', 'json')
        result = access.execute(self.request(source))
        self.assertEqual(result['status'], 'succeeded', result)
        self.assertEqual(result['scope'], 'data')
        table = result['tables'][0]
        self.assertEqual(table['sampling'], {'method': 'bounded-records', 'rowCount': 2, 'limit': 2,
                                           'byteLimit': 1048576, 'truncated': True})
        columns = {c['name']: c for c in table['columns']}
        self.assertEqual(columns['id']['type'], 'integer')
        self.assertEqual((columns['price']['precision'], columns['price']['scale']), (38, 3))
        self.assertTrue(all(c['nullable'] and not c.get('key') for c in columns.values()))
        self.assertNotIn('PRIVATE_', json.dumps(result))
        self.assertNotIn('rows', json.dumps(result))

    def test_ambiguous_nested_null_and_range_fields_are_explicitly_unsupported(self):
        _, source = self.fixture('{"nested":{"secret":"PRIVATE_NESTED"},"array":[1],"blank":null,"mix":1,"big":9223372036854775808,"dec":1e100}\n'
                                 '{"nested":{},"array":[],"blank":null,"mix":"two","big":9223372036854775809,"dec":1e99}\n')
        result = access.execute(self.request(source))
        self.assertEqual(result['status'], 'succeeded', result)
        fields = {c['name']: c for c in result['tables'][0]['columns']}
        self.assertEqual({n:c['sourceType'] for n,c in fields.items()},
                         {'nested':'nested-object','array':'nested-array','blank':'all-null','mix':'mixed-types',
                          'big':'integer-outside-int64','dec':'decimal-outside-precision38'})
        self.assertTrue(all(c['supported'] is False for c in fields.values()))
        self.assertNotIn('PRIVATE_NESTED', json.dumps(result))

    def test_scalar_overrides_and_decimal_combined_precision(self):
        _, source = self.fixture('{"id":"1","blank":null,"value":1234567890123456789012345678901234567.0}\n'
                                 '{"id":"2","blank":null,"value":0.00000000001}\n')
        source['types'] = {'id':'integer','blank':'string'}
        result = access.execute(self.request(source))
        self.assertEqual(result['status'], 'succeeded', result)
        fields = {c['name']: c for c in result['tables'][0]['columns']}
        self.assertEqual(fields['id']['type'], 'integer')
        self.assertEqual(fields['blank']['type'], 'string')
        self.assertEqual(fields['value']['sourceType'], 'decimal-outside-precision38')

    def test_invalid_prefixes_and_later_table_failure_leave_no_partial_metadata(self):
        for fmt, text in [('json','[{"id":1},]'),('json','[{"id":1}]garbage'),('json','[{"id":1}'),
                          ('jsonl','{"id":1,"id":2}\n'),('jsonl','{"id":NaN}\n'),
                          ('jsonl','\n'),('jsonl','{"id":1}\n{"different":2}\n'),('json','[]')]:
            _, source = self.fixture(text, fmt)
            result = access.execute(self.request(source))
            self.assertEqual(result['status'], 'failed', (fmt, text, result))
            self.assertEqual(result['tables'], [])
        _, good = self.fixture('{"id":1}\n')
        _, bad = self.fixture('PRIVATE_BROKEN')
        result = access.execute(self.request(good, tables=[good,bad]))
        self.assertEqual(result['tables'], [])
        self.assertNotIn('PRIVATE_BROKEN', json.dumps(result))

    def test_byte_bound_and_prefix_sampling_do_not_parse_the_unread_suffix(self):
        _, source = self.fixture('{"id":1}\n{"id":2}\n{"id":3}\n' + 'PRIVATE_INVALID_SUFFIX' * 100000)
        result = access.execute(self.request(source))
        self.assertEqual(result['status'], 'succeeded', result)
        self.assertTrue(result['tables'][0]['sampling']['truncated'])
        _, large = self.fixture('{"id":"' + 'x' * 1048576 + '"}\n')
        result = access.execute(self.request(large))
        self.assertEqual(result['code'], 'SAMPLE_TOO_LARGE')
        class CountingBytes(io.BytesIO):
            total = 0
            def read(self, size=-1):
                self.assert_size = size
                if size < 0: raise AssertionError('unbounded read')
                part=super().read(size);self.total += len(part);return part
        handle=CountingBytes(b'{"id":"' + b'x' * 1048576 + b'"}\n')
        with self.assertRaises(sample.AccessError): list(sample.records(handle,'jsonl'))
        self.assertLessEqual(handle.total,1048577)

    def test_symlink_and_source_replacement_are_refused_without_values(self):
        path, source = self.fixture('{"id":1}\n')
        link=path.parent/'link.jsonl';link.symlink_to(path)
        result=access.execute(self.request({**source,'path':str(link)}))
        self.assertEqual(result['status'],'failed')
        original=sample.records
        def replace(handle, fmt):
            for row in original(handle,fmt):
                yield row
            path.write_text('{"id":2,"secret":"PRIVATE_CHANGED"}\n')
        with patch.object(sample,'records',replace): result=access.execute(self.request(source))
        self.assertEqual(result['code'],'ACCESS_CHANGED')
        self.assertNotIn('PRIVATE_CHANGED',json.dumps(result))

class FilesDataSample(unittest.TestCase):
    fixture = FilesSchemaSample.fixture
    def preview(self, source, **values):
        return access.execute({'connector':'files','action':'sample','settings':{},
                               'source':source,'limit':2, **values})

    def test_large_json_and_jsonl_prefixes_return_exact_selected_values(self):
        for fmt, text in [('json', '[{"id":9223372036854775807,"price":12.340},'
                           '{"id":2,"price":0.01},{"id":3,"price":0.02},' + 'PRIVATE_UNREAD' * 100000),
                          ('jsonl', '{"id":9223372036854775807,"price":12.340}\n'
                           '{"id":2,"price":0.01}\n{"id":3,"price":0.02}\n' + 'PRIVATE_UNREAD' * 100000)]:
            path, source=self.fixture(text,fmt)
            self.assertGreater(path.stat().st_size,1048576)
            result=self.preview(source,columns=['price','id'])
            self.assertEqual(result['status'],'succeeded',result)
            self.assertEqual(result['sample'],{'columns':['price','id'],
                             'rows':[['12.340','9223372036854775807'],['0.01',2]],'truncated':True})
            self.assertNotIn('PRIVATE_UNREAD',json.dumps(result))

    def test_invalid_selection_and_limit_do_not_open_files(self):
        _,source=self.fixture('{"id":1}\n')
        for values in ({'limit':False},{'limit':0},{'limit':51},{'columns':[]},
                       {'columns':['id','id']},{'columns':[1]},{'columns':['id']*101},
                       {'settings':{'private':'PRIVATE_SETTINGS'}}):
            with patch.object(sample.os,'open',side_effect=AssertionError('must not read')):
                result=self.preview(source,**values)
            self.assertEqual(result['status'],'failed')
            self.assertNotIn('sample',result)
            self.assertNotIn('PRIVATE_SETTINGS',json.dumps(result))

    def test_selected_scalars_can_exclude_nested_fields_and_are_cell_bounded(self):
        _,source=self.fixture(json.dumps({'id':1,'text':'😀'*600,'nested':{'secret':'PRIVATE_NESTED'}})+'\n')
        result=self.preview(source,columns=['text','id'])
        self.assertEqual(result['status'],'succeeded',result)
        self.assertLessEqual(len(result['sample']['rows'][0][0].encode('utf-16-le')),1000)
        self.assertEqual(result['sample']['rows'][0][1],1)
        self.assertFalse(result['sample']['truncated'])
        self.assertNotIn('PRIVATE_NESTED',json.dumps(result))
        for columns in (['nested'], None):
            result=self.preview(source,columns=columns)
            self.assertEqual(result['status'],'succeeded',result)
            self.assertIn('PRIVATE_NESTED',json.dumps(result['sample']))
        result=self.preview(source,columns=['missing'])
        self.assertEqual(result['status'],'failed')
        self.assertNotIn('sample',result)
        self.assertNotIn('PRIVATE_NESTED',json.dumps(result))

    def test_malformed_prefix_and_byte_bound_return_no_partial_business_rows(self):
        for fmt,text in [('jsonl','{"id":1}\nPRIVATE_MALFORMED'),
                         ('json','[{"id":1},]'),('jsonl','{"id":1}\n{"other":2}\n'),
                         ('jsonl','{"id":1,"id":2}\n'),('jsonl','{"id":Infinity}\n'),
                         ('jsonl','{"id":"'+'x'*1048576+'"}\n')]:
            _,source=self.fixture(text,fmt);result=self.preview(source)
            self.assertEqual(result['status'],'failed',(fmt,result))
            self.assertNotIn('sample',result)
            self.assertNotIn('PRIVATE_MALFORMED',json.dumps(result))

    def test_preview_replacement_and_lookahead_rewrite_are_fenced(self):
        for text in ('{"id":1}\n','{"id":1}\n{"id":2}\n{"id":3}\n'):
            path,source=self.fixture(text);original=sample.records
            def replaced(handle,fmt):
                for index,row in enumerate(original(handle,fmt),1):
                    if index == 3:
                        path.write_text('{"id":2,"secret":"PRIVATE_CHANGED"}\n')
                    yield row
                path.write_text('{"id":2,"secret":"PRIVATE_CHANGED"}\n')
            with patch.object(sample,'records',replaced):result=self.preview(source)
            self.assertEqual(result['code'],'ACCESS_CHANGED',result)
            self.assertNotIn('sample',result)
            self.assertNotIn('PRIVATE_CHANGED',json.dumps(result))

    def test_opened_replacement_cannot_change_the_reviewed_file(self):
        path,source=self.fixture('{"id":1}\n');original=sample.os.open
        def replaced(*args,**kwargs):
            replacement=path.parent/'replacement.jsonl';replacement.write_text('{"id":2}\n')
            replacement.replace(path)
            return original(*args,**kwargs)
        with patch.object(sample.os,'open',replaced):result=self.preview(source)
        self.assertEqual(result['code'],'ACCESS_CHANGED',result)
        self.assertNotIn('sample',result)

if __name__ == '__main__': unittest.main()
