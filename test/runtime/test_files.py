from pathlib import Path
import tempfile
import unittest
import sys
from decimal import Decimal
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'runtime'))
from files_reader import scan, MAX_BYTES
import pyarrow as pa
import pyarrow.parquet as pq

class Files(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
 def tearDown(self): self.temp.cleanup()
 def read(self,fmt,content,types=None):
  p=self.root/('input.'+fmt)
  if isinstance(content,bytes):p.write_bytes(content)
  else:p.write_text(content)
  rows=[];schema,count=scan({'path':str(p),'format':fmt,'types':types or {}},rows.append)
  return rows,schema,count
 def test_delimited_quotes_newlines_null_and_decimal(self):
  rows,schema,n=self.read('csv','id,name,amount,email\n1,"Café\nShop",12.50,\n',{'id':'integer','amount':'decimal'})
  self.assertEqual(rows,[{'id':1,'name':'Café\nShop','amount':Decimal('12.50'),'email':None}]);self.assertEqual(n,1)
  self.assertEqual(schema['properties']['id']['type'],['null','integer'])
  rows,_,_=self.read('tsv','id\tactive\n2\tfalse\n',{'id':'integer','active':'boolean'})
  self.assertEqual(rows,[{'id':2,'active':False}])
 def test_json_and_jsonl(self):
  for fmt,text in [('json','[{"id":1,"price":12.50}]'),('jsonl','{"id":1,"price":12.50}\n')]:
   rows,_,_=self.read(fmt,text);self.assertEqual(rows,[{'id':1,'price':Decimal('12.50')}])
 def test_parquet(self):
  p=self.root/'in.parquet';pq.write_table(pa.table({'id':[1,2],'price':pa.array([Decimal('12.50'),None],pa.decimal128(10,2))}),p)
  rows=[];_,n=scan({'path':str(p),'format':'parquet'},rows.append);self.assertEqual(n,2);self.assertEqual(rows[0]['price'],Decimal('12.50'))
 def test_empty(self):
  for fmt,body,types in [('csv','id\n',{}),('json','[]',{'id':'integer'}),('jsonl','',{'id':'integer'})]:
   rows,schema,n=self.read(fmt,body,types);self.assertEqual(n,0);self.assertIn('id',schema['properties'])
 def test_malformed_and_ambiguous_rejected(self):
  cases=[('csv','id,id\n1,2\n',{}),('csv','id,name\n1\n',{}),('json','[{"id":1,"id":2}]',{}),('json','[{"a":{"b":1}}]',{}),('json','[{"id":1},{"id":"two"}]',{}),('json','[{"id":1},{"id":2,"new":3}]',{}),('json','[{"id":NaN}]',{}),('csv','id\n01\n',{'id':'integer'}),('json','[]',{}),('csv','id\n1\n',{'absent':'integer'})]
  for fmt,body,types in cases:
   with self.subTest(body=body),self.assertRaises(ValueError):self.read(fmt,body,types)
 def test_paths_and_size(self):
  p=self.root/'file.csv';p.write_text('id\n1\n');link=self.root/'link.csv';link.symlink_to(p)
  for target in [link,self.root,self.root/'missing',Path('relative.csv')]:
   with self.subTest(target=target),self.assertRaises((ValueError,OSError)):scan({'path':str(target),'format':'csv'})
  with p.open('wb') as f:f.truncate(MAX_BYTES+1)
  with self.assertRaises(ValueError):scan({'path':str(p),'format':'csv'})
 def test_mutation_during_read(self):
  p=self.root/'in.json';p.write_text('[{"id":1}]')
  with self.assertRaisesRegex(ValueError,'changed during read'):
   scan({'path':str(p),'format':'json'},lambda _:p.write_text('[{"id":2}]'))
