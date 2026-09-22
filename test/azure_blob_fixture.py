"""Loopback Azure transport for installed-package tests; never a runtime asset."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,unquote
import threading,hashlib
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_HEAD(self):self.respond(False)
 def do_GET(self):self.respond(True)
 def respond(self,body):
  parts=unquote(urlsplit(self.path).path).split('/')
  if len(parts)!=6 or parts[1:4]!=['samples','retail','v1'] or parts[4] not in ('csv','tsv','json','jsonl','parquet') or '/' in parts[5] or parts[5].startswith('.'):
   self.send_error(404);return
  path=self.server.data/parts[4]/parts[5]
  if not path.is_file():self.send_error(404);return
  content=path.read_bytes();etag='"'+hashlib.sha256(content).hexdigest()+'"'
  self.server.observed.append(self.command)
  if self.server.mode['value']=='denied':self.send_error(403);return
  if body and (self.server.mode['value']=='changed' or self.headers.get('If-Match')!=etag):self.send_error(412);return
  self.send_response(200);self.send_header('Content-Length',str(len(content)));self.send_header('ETag',etag);self.end_headers()
  if body:self.wfile.write(content)
@contextmanager
def azure_blob_fixture(site,data):
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.data=data;server.mode={'value':'normal'};server.observed=[]
 thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 hook=site/'ingestron_blob_fixture.pth';code=site/'ingestron_blob_fixture.py'
 assert not hook.exists() and not code.exists()
 code.write_text('''import http.client,socket
class FixtureConnection(http.client.HTTPConnection):
 def __init__(self,host,timeout=30):
  if host!='sampleaccount.blob.core.windows.net':raise RuntimeError('Unexpected fixture host')
  super().__init__('127.0.0.1',PORT,timeout=timeout)
http.client.HTTPSConnection=FixtureConnection
_original=socket.socket.connect
def connect(self,address):
 if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1'):raise RuntimeError('External socket denied')
 return _original(self,address)
socket.socket.connect=connect
'''.replace('PORT',str(server.server_port)))
 hook.write_text('import ingestron_blob_fixture\n')
 try:yield server
 finally:
  hook.unlink();code.unlink();server.shutdown();server.server_close();thread.join()
