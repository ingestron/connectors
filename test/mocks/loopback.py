"""Serve an in-memory API mock to an installed runtime over loopback; tests only.

The runtime's HTTPSConnection is replaced (through a .pth hook in the prepared
environment) by a plain loopback connection that carries the intended host in a
header; every other socket is refused. Never part of a runtime asset.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _serve(self):
        host = self.headers.get('X-Ingestron-Host', '')
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length).decode() if length else None
        headers = {k: v for k, v in self.headers.items() if k != 'X-Ingestron-Host'}
        status, data = self.server.handle(host, self.command, self.path, headers, body)
        data = data if isinstance(data, bytes) else __import__('json').dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = _serve


@contextmanager
def loopback(site, handle, hosts):
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.handle = handle
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    hook, code = site / 'ingestron_loopback.pth', site / 'ingestron_loopback.py'
    assert not hook.exists() and not code.exists()
    code.write_text(f'''import http.client, socket
HOSTS = {sorted(hosts)!r}
class LoopbackConnection(http.client.HTTPConnection):
    def __init__(self, host, timeout=30):
        if host not in HOSTS: raise RuntimeError('Unexpected fixture host')
        self._target = host
        super().__init__('127.0.0.1', {server.server_port}, timeout=timeout)
    def request(self, method, url, body=None, headers=None):
        super().request(method, url, body=body, headers={{**(headers or {{}}), 'X-Ingestron-Host': self._target}})
http.client.HTTPSConnection = LoopbackConnection
_connect = socket.socket.connect
def connect(self, address):
    if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', '::1'):
        raise RuntimeError('External socket denied')
    return _connect(self, address)
socket.socket.connect = connect
''')
    hook.write_text('import ingestron_loopback\n')
    try:
        yield server
    finally:
        hook.unlink()
        code.unlink()
        server.shutdown()
        server.server_close()
        thread.join()
