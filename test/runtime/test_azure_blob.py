from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'runtime'))
import azure_blob_reader as reader

SETTINGS={'account':'sampleaccount','container':'samples','blob':'retail/a b.csv','sas_token':'sv=2023-11-03&sp=rl&se=2030-01-01&spr=https&sig=synthetic','format':'csv','types':{'id':'integer'}}
class Response:
 def __init__(self,status=200,body=b'id\n1\n',headers=None):
  self.status=status;self.body=body;self.headers={'ETag':'"v1"','Content-Length':str(len(body)),**(headers or {})}
 def getheader(self,k,default=None):return self.headers.get(k,default)
 def read(self,n):r=self.body[:n];self.body=self.body[n:];return r
 def close(self):pass
class Connection:
 responses=[];requests=[]
 def __init__(self,host,timeout):self.host=host
 def request(self,method,target,headers):self.requests.append((self.host,method,target,headers))
 def getresponse(self):return self.responses.pop(0)
 def close(self):pass
class AzureBlob(unittest.TestCase):
 def setUp(self):Connection.responses=[Response(),Response()];Connection.requests=[]
 def run_scan(self):
  with patch.object(reader.http.client,'HTTPSConnection',Connection):
   rows=[];schema,n=reader.scan(SETTINGS,rows.append);return rows,n
 def test_read_uses_if_match_and_existing_reader(self):
  rows,n=self.run_scan();self.assertEqual(rows,[{'id':1}]);self.assertEqual(n,1)
  a,b=Connection.requests;self.assertEqual(a[0],'sampleaccount.blob.core.windows.net');self.assertEqual(a[1],'HEAD');self.assertEqual(b[1],'GET');self.assertEqual(b[3]['If-Match'],'"v1"');self.assertIn('/retail/a%20b.csv?',b[2])
 def test_redirect_auth_mutation_and_length_fail_closed(self):
  cases=[(0,Response(status=302)),(0,Response(status=403)),(1,Response(status=412)),(1,Response(headers={'ETag':'"v2"'})),(0,Response(headers={'Content-Length':str(reader.MAX_BYTES+1)})),(1,Response(body=b'id\n',headers={'Content-Length':'5'})),(1,Response(body=b'id\n1\nEXTRA',headers={'Content-Length':'5'})),(1,Response(headers={'Content-Encoding':'gzip'})),(0,Response(headers={'x-ms-resource-type':'directory'}))]
  for index,response in cases:
   Connection.responses=[Response(),Response()];Connection.responses[index]=response
   with self.subTest(index=index,status=response.status),self.assertRaises(ValueError) as error:self.run_scan()
   self.assertNotIn('synthetic',str(error.exception))
 def test_endpoint_path_and_sas_validation(self):
  cases=[('account','evil.example'),('container','../x'),('blob','../file'),('blob','a//b'),('blob','/a'),('blob','a\n'),('sas_token',SETTINGS['sas_token']+'&comp=list'),('sas_token',SETTINGS['sas_token']+'&sig=duplicate'),('sas_token',SETTINGS['sas_token'].replace('sp=rl','sp=rwd')),('sas_token',SETTINGS['sas_token'].replace('spr=https','spr=http'))]
  for key,value in cases:
   with self.subTest(key=key),self.assertRaises(ValueError):reader.request_target({**SETTINGS,key:value})
 def test_network_error_does_not_expose_token(self):
  with patch.object(reader.http.client,'HTTPSConnection',side_effect=OSError('secret synthetic')),self.assertRaises(ValueError) as error:reader.scan(SETTINGS)
  self.assertNotIn('synthetic',str(error.exception))
 def test_failed_download_removes_private_temporary_file(self):
  paths=[]
  def fail(settings,path):paths.append(path);path.write_text('private');raise ValueError('failed')
  with patch.object(reader,'download',fail),self.assertRaises(ValueError):reader.scan(SETTINGS)
  self.assertFalse(paths[0].exists());self.assertFalse(paths[0].parent.exists())
