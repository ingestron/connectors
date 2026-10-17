"""Source-native temporal metadata, loss prevention and unchanged wire schemas."""
from datetime import date,datetime,timezone
from pathlib import Path
import json,socket,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'runtime'))
import dbapi_reader as dbapi
import sql_server_reader as sql
from source_sample import database_sample,SampleError

class Cursor:
    def __init__(self,rows,values=()):self.rows=rows;self.values=values;self.queries=[];self.sent=False
    def execute(self,query,parameters=()):self.queries.append((query,parameters))
    def fetchall(self):
        query=self.queries[-1][0]
        if 'PRIMARY KEY' in query or "CONSTRAINT_NAME = 'PRIMARY'" in query or 'all_constraints' in query:return [('id',)]
        return self.rows
    def fetchmany(self,size):
        if self.sent:return []
        self.sent=True;return self.values[:size]

class Database:
    def __init__(self,rows,values=()):self.c=Cursor(rows,values);self.closed=False
    def cursor(self):return self.c
    def close(self):self.closed=True

CONNECTION={'host':'db.example.invalid','database':'fixture','user':'reader','password':'synthetic-only'}
SQL_CONNECTION={'server':'db.example.invalid','database':'fixture','authentication':{'method':'sql-password','username':'reader','password':'synthetic-only'}}
TABLE={'schema':'synthetic','table':'dates'}

class DatabaseTemporal(unittest.TestCase):
    def setUp(self):
        self.network=patch.object(socket,'create_connection',side_effect=AssertionError('No network permitted'))
        self.network.start()
    def tearDown(self):self.network.stop()
    def test_three_db_catalogues_preserve_native_semantics_and_only_read_system_metadata(self):
        fixtures={
            'postgresql':[('id','integer',32,0,'NO'),('day','date',None,None,'YES'),('event','timestamp without time zone',None,6,'YES'),('zoned','timestamp with time zone',None,6,'YES')],
            'mysql':[('id','int',10,0,'NO'),('day','date',None,None,'YES'),('event','datetime',None,6,'YES'),('session','timestamp',None,6,'YES')],
            'oracle':[('id','NUMBER',10,0,'N'),('day','DATE',None,None,'Y'),('event','TIMESTAMP(6)',None,6,'Y'),('zoned','TIMESTAMP(6) WITH TIME ZONE',None,6,'Y'),('local','TIMESTAMP(6) WITH LOCAL TIME ZONE',None,6,'Y'),('precise','TIMESTAMP(9)',None,9,'Y')],
        }
        for dialect,rows in fixtures.items():
            with self.subTest(dialect=dialect):
                db=Database(rows);columns=dbapi.catalogue(dialect,CONNECTION,TABLE,connect=lambda _:db)
                self.assertEqual(columns[1]['type'],'timestamp' if dialect=='oracle' else 'date')
                self.assertEqual(columns[2]['type'],'timestamp');self.assertTrue(columns[0]['key'])
                self.assertTrue(columns[1]['nullable']);self.assertFalse(columns[0]['nullable'])
                if dialect=='oracle':
                    for c in columns[3:]:self.assertFalse(c['supported'])
                else:self.assertEqual(columns[3]['type'],'string')
                self.assertEqual(len(db.c.queries),2)
                self.assertTrue(all('synthetic.dates' not in q and parameters==('synthetic','dates') for q,parameters in db.c.queries))
                self.assertTrue(db.closed);self.assertNotIn('synthetic-only',json.dumps(columns))
                if dialect!='oracle':self.assertIn('datetime_precision',db.c.queries[0][0].lower())
    def test_sql_catalogue_distinguishes_calendar_time_precision_offsets_and_binary_rowversion(self):
        rows=[('id','int',10,0,False,True),('day','date',10,0,True,False),('event','datetime2',27,6,True,False),('legacy','datetime',23,3,True,False),('minute','smalldatetime',16,0,True,False),('precise','datetime2',27,7,True,False),('zoned','datetimeoffset',34,7,True,False),('version','timestamp',0,0,False,False)]
        db=Database(rows);columns=sql.catalogue({'connection':SQL_CONNECTION,'object':TABLE},connect=lambda *a,**k:db)
        self.assertEqual([c['type'] for c in columns[:5]],['integer','date','timestamp','timestamp','timestamp'])
        self.assertFalse(columns[5]['supported']);self.assertEqual(columns[5]['sourceType'],'datetime2(7)')
        self.assertEqual(columns[6]['type'],'string');self.assertFalse(columns[7]['supported'])
        self.assertIn('FROM sys.tables',db.c.queries[0][0]);self.assertEqual(len(db.c.queries),1);self.assertTrue(db.closed)
    def test_db_scans_keep_string_wire_types_exact_temporal_text_and_nulls(self):
        for dialect,source_type in [('postgresql','timestamp without time zone'),('mysql','datetime'),('oracle','TIMESTAMP(6)')]:
            with self.subTest(dialect=dialect):
                nullable='Y' if dialect=='oracle' else 'YES'
                db=Database([('event',source_type,None,6,nullable)],[(datetime(2024,2,29,1,2,3,123456),),(None,)])
                records=[];schema,count=dbapi.scan(dialect,CONNECTION,TABLE,records.append,lambda _:db)
                self.assertEqual(schema['properties']['event']['type'],['null','string'])
                self.assertEqual(records,[{'event':'2024-02-29T01:02:03.123456'},{'event':None}]);self.assertEqual(count,2);self.assertTrue(db.closed)
        db=Database([('event','datetime2',27,6,True)],[(datetime(2024,2,29,1,2,3,123456),)])
        records=[];schema,count=sql.scan({'connection':SQL_CONNECTION,'object':TABLE},records.append,lambda *a,**k:db)
        self.assertEqual(schema['properties']['event']['type'],['null','string']);self.assertEqual(records[0]['event'],'2024-02-29T01:02:03.123456')
    def test_unsafe_precision_and_oracle_timezones_fail_before_any_record_read(self):
        for source_type,scale in [('TIMESTAMP(9)',9),('TIMESTAMP(6) WITH TIME ZONE',6),('TIMESTAMP(6) WITH LOCAL TIME ZONE',6)]:
            db=Database([('event',source_type,None,scale,'Y')]);records=[]
            with self.assertRaises(ValueError):dbapi.scan('oracle',CONNECTION,TABLE,records.append,lambda _:db)
            self.assertEqual(len(db.c.queries),1);self.assertEqual(records,[]);self.assertTrue(db.closed)
        for scale in [None,7]:
            db=Database([('event','datetime2',27,scale,True)])
            with self.assertRaisesRegex(ValueError,'precision'):sql.scan({'connection':SQL_CONNECTION,'object':TABLE},lambda _:self.fail('No records'),lambda *a,**k:db)
            self.assertEqual(len(db.c.queries),1);self.assertTrue(db.closed)
    def test_bounded_samples_refuse_unsupported_selected_precision_before_second_connection(self):
        db=Database([('event','datetime2',27,7,True,False)]);calls=[]
        def connect(*args,**kwargs):calls.append(1);return db
        with self.assertRaises(SampleError):database_sample('sql-server',{'connection':SQL_CONNECTION},{'source':TABLE,'columns':['event'],'limit':2},connect)
        self.assertEqual(len(calls),1);self.assertEqual(len(db.c.queries),1);self.assertTrue(db.closed)
    def test_string_timezone_values_retain_offset_and_oracle_date_retains_time_of_day(self):
        zoned=datetime(2024,2,29,1,2,3,123456,tzinfo=timezone.utc)
        self.assertEqual(dbapi.wire_value(zoned,'string'),'2024-02-29T01:02:03.123456+00:00')
        self.assertEqual(sql.wire_value(zoned,'string'),'2024-02-29T01:02:03.123456+00:00')
        native=datetime(2024,2,29,1,2,3)
        self.assertEqual(dbapi.temporal_type('oracle','DATE',None),'timestamp')
        self.assertEqual(dbapi.wire_value(native,'string'),'2024-02-29T01:02:03')

if __name__=='__main__':unittest.main()
