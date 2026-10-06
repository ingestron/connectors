from pathlib import Path
from datetime import date, datetime, timezone
import sys, json, tempfile, unittest,io
from contextlib import redirect_stdout
from unittest.mock import patch
import pyarrow as pa
import pyarrow.parquet as pq
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'runtime'))
from temporal_types import TemporalError, MESSAGES
import singer_runtime as runtime
from singer_bridge import convert, arrow_type, temporal_value, snapshot, digest
from singer_runtime import project_selection, review
from quality_rules import _values
import files_reader as reader
import files_access

class Temporal(unittest.TestCase):
    def test_temporal_failures_cross_the_runtime_boundary_with_static_codes(self):
        cases=[('PRIVATE_RECORD','date','TEMPORAL_DATE'),('2024-02-30T01:02:03','timestamp','TEMPORAL_TIMESTAMP'),('2024-02-29T01:02:03Z','timestamp','TEMPORAL_TIMEZONE'),('2024-02-29T01:02:03.1234567','timestamp','TEMPORAL_PRECISION')]
        for value,kind,code in cases:
            with self.subTest(code=code):
                with self.assertRaises(TemporalError) as caught:temporal_value(value,kind)
                self.assertEqual(caught.exception.code,code)
                stdout=io.StringIO()
                def failed(*args):raise TemporalError(code)
                with patch.object(sys,'argv',['source','catalogue']),patch.object(runtime,'load',return_value={}),patch.object(runtime,'catalogue',side_effect=failed),redirect_stdout(stdout):
                    with self.assertRaises(SystemExit) as stopped:runtime.main()
                self.assertEqual(stopped.exception.code,1)
                result=json.loads(stdout.getvalue());self.assertEqual(result['errorCode'],code);self.assertEqual(result['error'],MESSAGES[code]);self.assertNotIn('PRIVATE_RECORD',json.dumps(result));self.assertNotIn('1234567',json.dumps(result))
    def test_calendar_validation_is_exact_and_errors_never_echo_values(self):
        self.assertEqual(temporal_value('2024-02-29','date'),date(2024,2,29))
        for value in ['2023-02-29','2024-13-01','20240229','2024-02-29T01:00:00',' PRIVATE_TEMPORAL',datetime(2024,2,29),123,True]:
            with self.assertRaises(ValueError) as caught: temporal_value(value,'date')
            self.assertNotIn('PRIVATE_TEMPORAL',str(caught.exception))
    def test_timestamp_rejects_offsets_overprecision_and_invalid_calendars(self):
        self.assertEqual(temporal_value('2024-02-29T23:59:59.123456','timestamp'),datetime(2024,2,29,23,59,59,123456))
        for value in ['2024-02-29T23:59:59.1234567','2024-02-29T23:59:59Z','2024-02-29T23:59:59+13:00','2024-02-30T00:00:00','2024-02-29T23:59:60','2024-02-29',datetime.now(timezone.utc)]:
            with self.assertRaises(ValueError): temporal_value(value,'timestamp')
    def test_projection_writes_native_temporal_parquet_without_precision_loss(self):
        fields={'day':{'type':'date','nullable':False},'event':{'type':'timestamp','nullable':True}}
        data=pa.table({name:pa.array([convert(value,fields[name])],type=arrow_type(fields[name])) for name,value in [('day','2024-02-29'),('event','2024-02-29T01:02:03.123456')]})
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'output.parquet';pq.write_table(data,path);restored=pq.read_table(path)
            self.assertEqual(restored.schema.field('day').type,pa.date32())
            self.assertEqual(restored.schema.field('event').type,pa.timestamp('us'))
            self.assertEqual(restored.to_pylist(),[{'day':date(2024,2,29),'event':datetime(2024,2,29,1,2,3,123456)}])
        self.assertIsNone(convert(None,fields['event']))
        with self.assertRaisesRegex(ValueError,'Required'): convert(None,fields['day'])
    def test_snapshot_buffers_native_temporal_values_and_commits_exact_parquet(self):
        schema={'type':'object','properties':{'day':{'type':'string'},'event':{'type':['null','string']}}}
        fields={'day':{'type':'date','nullable':False},'event':{'type':'timestamp','nullable':True}}
        contract={'dates':{'schema_sha256':digest(schema),'fields':fields}}
        def messages():
            yield {'type':'SCHEMA','stream':'dates','schema':schema}
            yield {'type':'RECORD','stream':'dates','record':{'day':'2024-02-29','event':'2024-02-29T01:02:03.123456'}}
            yield {'type':'RECORD','stream':'dates','record':{'day':'2024-03-01','event':None}}
        with tempfile.TemporaryDirectory() as folder:
            snapshot(folder,'temporal','native',contract,{},messages)
            restored=pq.read_table(Path(folder)/'temporal/native/dates.parquet')
            self.assertEqual(restored.to_pylist(),[{'day':date(2024,2,29),'event':datetime(2024,2,29,1,2,3,123456)},{'day':date(2024,3,1),'event':None}])
    def test_contract_projection_retains_reviewed_types_mapping_and_nullable(self):
        selection=project_selection({'tables':{'dates':{'source':{'stream':'dates'},'columns':[{'name':'day','type':'DATE','required':True,'target':'business_day'},{'name':'event','type':'TIMESTAMP','required':False}]}}})
        self.assertEqual(selection['dates']['fields'],{'day':{'type':'date','nullable':False,'target':'business_day'},'event':{'type':'timestamp','nullable':True}})
    def test_delimited_types_require_explicit_review_and_reject_invalid_last_row(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve()/'input.csv';path.write_text('day,event\n2024-02-29,2024-02-29T01:02:03.123456\n')
            settings={'path':str(path),'format':'csv','types':{'day':'date','event':'timestamp'}}
            rows=[];schema,count=reader.scan(settings,rows.append);self.assertEqual(count,1)
            self.assertEqual(rows,[{'day':'2024-02-29','event':'2024-02-29T01:02:03.123456'}])
            self.assertEqual(schema['properties']['day']['format'],'date')
            self.assertNotIn('format',schema['properties']['event'])
            path.write_text(path.read_text()+'2023-02-29,2024-02-29T01:02:03\n')
            with self.assertRaisesRegex(ValueError,'calendar'):reader.scan(settings)
    def test_parquet_metadata_and_samples_preserve_source_temporal_types(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve()/'input.parquet';pq.write_table(pa.table({'day':pa.array([date(2024,2,29),date(2024,3,1)],type=pa.date32()),'event':pa.array([datetime(2024,2,29,1,2,3,123456),None],type=pa.timestamp('us'))}),path)
            source={'path':str(path),'format':'parquet'}
            metadata=files_access.execute({'connector':'files','settings':{},'action':'metadata','tables':[source]})
            self.assertEqual(metadata['status'],'succeeded',metadata)
            self.assertEqual([c['type'] for c in metadata['tables'][0]['columns']],['date','timestamp'])
            sample=files_access.execute({'connector':'files','settings':{},'action':'sample','source':source,'limit':1})
            self.assertEqual(sample['sample']['rows'],[['2024-02-29','2024-02-29T01:02:03.123456']])
            self.assertTrue(sample['sample']['truncated'])
            rows=[];schema,count=reader.scan({**source,'types':{'day':'date','event':'timestamp'}},rows.append)
            self.assertEqual(count,2);self.assertIsNone(rows[1]['event'])
    def test_zoned_and_nanosecond_parquet_are_rejected_without_conversion(self):
        for native in [pa.timestamp('ns'),pa.timestamp('us',tz='UTC')]:
            with self.assertRaises(ValueError):reader.arrow_kind(native)
    def test_temporal_valid_values_use_typed_matches_and_ignore_invalid_values(self):
        dates=pa.chunked_array([[date(2024,2,29)]],type=pa.date32())
        self.assertEqual(_values(dates,['2024-02-29','2023-02-29','PRIVATE_BAD_DATE']).to_pylist(),[date(2024,2,29)])
        events=pa.chunked_array([[datetime(2024,2,29,1,2,3,123456)]],type=pa.timestamp('us'))
        self.assertEqual(_values(events,['2024-02-29T01:02:03.123456','2024-02-29T01:02:03Z']).to_pylist(),[datetime(2024,2,29,1,2,3,123456)])
    def test_date_and_timestamp_are_not_guessed_from_json_string_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve()/'input.json';path.write_text('[{"day":"2024-02-29","event":"2024-02-29T01:02:03"}]')
            schema,_=reader.scan({'path':str(path),'format':'json'})
            self.assertEqual(schema['properties']['day'],{'type':['null','string']})
            self.assertEqual(schema['properties']['event'],{'type':['null','string']})

if __name__=='__main__':unittest.main()
