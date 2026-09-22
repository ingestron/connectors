"""Synthetic loopback transport. Never included in a connector runtime bundle."""
import json
import threading
from textwrap import dedent
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from contextlib import contextmanager
requests=[]
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_POST(self):
        requests.append(self.path)
        if urlparse(self.path).path != '/graphql': self.send_error(400); return
        self.rfile.read(int(self.headers.get('Content-Length','0')))
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
        self.wfile.write(json.dumps({'data':{'repo0':{'nameWithOwner':'demo/repo','databaseId':1},'rateLimit':{'cost':1}}}).encode())
    def do_GET(self):
        url=urlparse(self.path);requests.append(self.path)
        if url.path in ('/repos/demo/repo/issues','/repositories/1/issues'):
            page='2' if 'after' in parse_qs(url.query) else '1'
            value=[{'id':int(page),'number':int(page),'title':'Issue '+page,'state':'open','type':None,'body':None,'updated_at':'2026-01-01T00:00:00Z'}]
            self.send_response(200)
            if page=='1': self.send_header('Link',f'<http://127.0.0.1:{self.server.server_port}/repos/demo/repo/issues?after=next>; rel="next"')
        elif url.path=='/rate_limit':
            value={};self.send_response(200)
        elif url.path=='/repos/demo/repo':
            value={'id':1,'name':'repo','full_name':'demo/repo','owner':{'login':'demo'}};self.send_response(200)
        else:
            value={'error':'Unexpected synthetic request'};self.send_response(400)
        self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(value).encode())

@contextmanager
def github_fixture(site_packages):
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    # Test-only transport interposition catches the upstream hardcoded rate-limit URL.
    # It is never included in a prepared runtime or installed upstream package.
    site=site_packages/'ingestron_synthetic_transport.py'
    hook=site.with_name('ingestron_synthetic_transport.pth')
    assert not site.exists() and not hook.exists(), 'Refuse to overwrite an existing Python startup hook'
    hook.write_text('import ingestron_synthetic_transport\n')
    site.write_text(dedent("""
    import requests, socket
    from urllib.parse import urlparse
    _original=requests.sessions.Session.send
    def fixture(self, request, *args, **kwargs):
        url=request.url
        if url.startswith('https://api.github.com/'):
            url='http://127.0.0.1:PORT/'+url.split('https://api.github.com/',1)[1]
        if urlparse(url).hostname != '127.0.0.1': raise RuntimeError('External test request denied')
        request.url=url
        return _original(self,request,*args,**kwargs)
    requests.sessions.Session.send=fixture
    _connect=socket.socket.connect
    def local(self,address):
        if isinstance(address,tuple) and address[0] not in ('127.0.0.1','::1'): raise RuntimeError('External socket denied')
        return _connect(self,address)
    socket.socket.connect=local
    """).replace('PORT',str(server.server_port)))
    try:
        requests.clear()
        yield requests
    finally:
        site.unlink(missing_ok=True)
        hook.unlink(missing_ok=True)
        server.shutdown(); server.server_close(); thread.join()
