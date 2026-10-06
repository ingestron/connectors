import io
import json
from decimal import Decimal
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import pyarrow as pa
import pyarrow.parquet as pq
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'runtime'))
import files_access as access
import files_data_sample as sample
import files_schema_sample as schema_sample


class FilesDataFormats(unittest.TestCase):
    def source(self, fmt, text=None, table=None):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        path=Path(folder.name).resolve()/('records.'+fmt)
        if table is not None:pq.write_table(table,path,compression='NONE',row_group_size=2)
        else:path.write_text(text)
        return path,{'path':str(path),'format':fmt}
    def preview(self,source,**values):
        return access.execute({'connector':'files','action':'sample','settings':{},'source':source,'limit':2,**values})
    def metadata(self,source,**values):
        return access.execute({'connector':'files','action':'metadata','settings':{},'tables':[source],**values})
    def test_delimited_samples_preserve_quoted_newlines_order_nulls_and_truncation(self):
        for fmt,delimiter in [('csv',','),('tsv','\t')]:
            _,source=self.source(fmt,'id'+delimiter+'label\n1'+delimiter+'"first\nline"\n2'+delimiter+'\n3'+delimiter+'third\n')
            result=self.preview(source,columns=['label','id'])
            self.assertEqual(result['status'],'succeeded',result)
            self.assertEqual(result['sample'],{'columns':['label','id'],'rows':[['first\nline','1'],[None,'2']],'truncated':True})
            metadata=self.metadata(source)
            self.assertEqual(metadata['status'],'succeeded',metadata)
            self.assertEqual([field['name'] for field in metadata['tables'][0]['columns']],['id','label'])
    def test_metadata_consumes_header_only_and_parquet_footer_only(self):
        _,source=self.source('csv','id,label\nPRIVATE_BROKEN_BUSINESS_ROW\n')
        result=self.metadata(source);self.assertEqual(result['status'],'succeeded',result)
        self.assertNotIn('PRIVATE_BROKEN_BUSINESS_ROW',json.dumps(result))
        handle=io.BytesIO(b'"quoted\nheader",label\nPRIVATE_BUSINESS_ROW\n')
        import csv
        self.assertEqual(next(csv.reader(sample.header_lines(handle),strict=True)),['quoted\nheader','label'])
        self.assertEqual(handle.read(),b'PRIVATE_BUSINESS_ROW\n')
        table=pa.table({'id':[1,2],'label':['PRIVATE_FOOTER_STATISTICS','second']})
        path,source=self.source('parquet',table=table)
        class Tracking(io.BytesIO):
            reads=[]
            def read(self,size=-1):
                before=self.tell();value=super().read(size);self.reads.append((before,before+len(value)));return value
        payload=path.read_bytes();handle=Tracking(payload)
        _,schema=sample.parquet_metadata(handle);footer_start=len(payload)-8-int.from_bytes(payload[-8:-4],'little')
        self.assertEqual(schema.names,['id','label'])
        self.assertTrue(all(end<=4 or start>=footer_start for start,end in handle.reads),handle.reads)
        result=self.metadata(source);self.assertEqual(result['status'],'succeeded',result)
        self.assertNotIn('PRIVATE_FOOTER_STATISTICS',json.dumps(result))
    def test_parquet_selected_scalar_samples_retain_decimal_precision_int64_and_row_bounds(self):
        table=pa.table({'id':pa.array([9223372036854775807,2,3],type=pa.int64()),
                        'amount':pa.array([Decimal('12.30'),Decimal('0.01'),Decimal('9.99')],type=pa.decimal128(20,2)),
                        'label':['first','second','third']})
        _,source=self.source('parquet',table=table)
        result=self.preview(source,columns=['amount','id']);self.assertEqual(result['status'],'succeeded',result)
        self.assertEqual(result['sample'],{'columns':['amount','id'],'rows':[['12.30','9223372036854775807'],['0.01',2]],'truncated':True})
        fields={f['name']:f for f in self.metadata(source)['tables'][0]['columns']}
        self.assertEqual((fields['amount']['precision'],fields['amount']['scale']),(20,2))
        self.assertFalse(self.preview(source,limit=3)['sample']['truncated'])
    def test_invalid_selection_limits_prefix_and_header_return_no_partial_rows(self):
        _,source=self.source('csv','id,label\n1,PRIVATE_FIRST_ROW\n2\n')
        result=self.preview(source);self.assertEqual(result['status'],'failed');self.assertNotIn('sample',result);self.assertNotIn('PRIVATE_FIRST_ROW',json.dumps(result))
        for request in ({'limit':True},{'limit':51},{'columns':[]},{'columns':['id','id']},{'columns':[{}]},{'settings':{'secret':'PRIVATE_INPUT'}}):
            with patch.object(schema_sample.os,'open',side_effect=AssertionError('must not read')):result=self.preview(source,**request)
            self.assertEqual(result['status'],'failed');self.assertNotIn('PRIVATE_INPUT',json.dumps(result));self.assertNotIn('sample',result)
        for header in ('id,id\n','x'*65537+'\n','id,'+'field,'*500+'last\n','"unfinished\n'):
            _,bad=self.source('csv',header);result=self.metadata(bad);self.assertEqual(result['status'],'failed',result);self.assertEqual(result['tables'],[])
    def test_delimited_byte_budget_and_parquet_page_memory_budget_are_enforced(self):
        _,source=self.source('csv','id,label\n1,'+'x'*1048576+'\n')
        result=self.preview(source);self.assertEqual(result['code'],'SAMPLE_TOO_LARGE',result);self.assertNotIn('sample',result)
        counted=sample.BudgetReader(io.BytesIO(b'x'*1048577))
        with self.assertRaises(sample.AccessError):counted.read(-1)
        self.assertEqual(counted.total,1048577)
        table=pa.table({'id':[1,2,3],'label':['x'*1000]*3})
        _,source=self.source('parquet',table=table)
        with patch.object(sample,'MAX_UNCOMPRESSED',100):result=self.preview(source,columns=['label'])
        self.assertEqual(result['code'],'SAMPLE_TOO_LARGE',result);self.assertNotIn('sample',result)
    def test_all_format_reads_refuse_symlinks_and_changed_sources_without_payload(self):
        for fmt in ('csv','tsv','parquet'):
            delimiter='\t' if fmt=='tsv' else ','
            path,source=self.source(fmt,table=pa.table({'id':[1,2,3]}) if fmt=='parquet' else None,
                                    text='id'+delimiter+'label\n1'+delimiter+'PRIVATE_BEFORE\n2'+delimiter+'second\n')
            link=path.parent/('link.'+fmt);link.symlink_to(path)
            for method in (self.preview,self.metadata):
                self.assertEqual(method({**source,'path':str(link)})['status'],'failed')
            if fmt=='parquet':
                original=sample.parquet_metadata
                def changed(handle):
                    value=original(handle);path.write_bytes(b'PRIVATE_CHANGED_SOURCE');return value
                with patch.object(sample,'parquet_metadata',changed):result=self.metadata(source)
            else:
                original=sample.header_lines
                def changed(handle):
                    for line in original(handle):
                        path.write_text('id,label\nPRIVATE_CHANGED_SOURCE\n');yield line
                with patch.object(sample,'header_lines',changed):result=self.metadata(source)
            self.assertEqual(result['code'],'ACCESS_CHANGED',result);self.assertEqual(result['tables'],[])
            self.assertNotIn('PRIVATE_CHANGED_SOURCE',json.dumps(result))
    def test_changed_preview_sources_discard_all_previously_collected_values(self):
        for fmt in ('csv','tsv','parquet'):
            delimiter='\t' if fmt=='tsv' else ','
            path,source=self.source(fmt,table=pa.table({'id':[1,2,3],'label':['PRIVATE_ORIGINAL','second','third']}) if fmt=='parquet' else None,
                                    text='id'+delimiter+'label\n1'+delimiter+'PRIVATE_ORIGINAL\n2'+delimiter+'second\n3'+delimiter+'third\n')
            original=sample.cell;replaced=False
            def changed(value):
                nonlocal replaced
                result=original(value)
                if not replaced:
                    replacement=path.parent/'replacement';replacement.write_bytes(b'PRIVATE_REPLACEMENT');replacement.replace(path);replaced=True
                return result
            with patch.object(sample,'cell',changed):result=self.preview(source)
            self.assertEqual(result['code'],'ACCESS_CHANGED',result);self.assertNotIn('sample',result)
            self.assertNotIn('PRIVATE_ORIGINAL',json.dumps(result));self.assertNotIn('PRIVATE_REPLACEMENT',json.dumps(result))
    def test_malformed_final_file_clears_the_whole_metadata_selection(self):
        _,good=self.source('csv','id,label\n1,PRIVATE_VALID_ROW\n');_,bad=self.source('parquet','PRIVATE_BAD_PARQUET')
        result=self.metadata(good,tables=[good,bad]);self.assertEqual(result['status'],'failed');self.assertEqual(result['tables'],[])
        self.assertNotIn('PRIVATE_BAD_PARQUET',json.dumps(result));self.assertNotIn('PRIVATE_VALID_ROW',json.dumps(result))

if __name__ == '__main__':unittest.main()
