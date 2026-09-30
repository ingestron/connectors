"""An in-memory Microsoft Graph for tests; never a runtime asset (PB-064 phase 4).

Covers the documented shapes the Graph files connector uses: client-credentials
tokens, site lookup by path, site drives with webUrl, a user's drive, driveItem
lookup by path (file or folder facet), paged children with @odata.nextLink, and
pre-authenticated download URLs on the tenant's SharePoint host.
"""
import json
from urllib.parse import parse_qs, quote, unquote, urlsplit

TENANT = '11111111-2222-3333-4444-555555555555'
CLIENT = '66666666-7777-8888-9999-000000000000'
SITE_ID = 'contoso.sharepoint.com,aaaaaaaa-0000-0000-0000-000000000001,bbbbbbbb-0000-0000-0000-000000000002'


class GraphApi:
    def __init__(self, secret):
        self.secret, self.token = secret, 'graph-access-token'
        self.drives = {'drive-docs': {}, 'drive-user': {}}
        self.lists = {}
        self.fail, self.truncate, self.page_size, self.requests = {}, set(), 2, []

    def put(self, drive, path, content):
        self.drives[drive][path] = content

    def remove(self, drive, path):
        self.drives[drive].pop(path, None)

    def _item(self, drive, path):
        files = self.drives[drive]
        if path in files:
            return {'id': f'{drive}:{path}', 'name': path.rsplit('/', 1)[-1], 'size': len(files[path]), 'file': {},
                    '@microsoft.graph.downloadUrl':
                        f'https://contoso.sharepoint.com/_layouts/15/download.aspx?UniqueId={quote(drive + ":" + path)}&tempauth=secret-tempauth'}
        if any(p.startswith(path + '/') for p in files):
            return {'id': f'{drive}:{path}', 'name': path.rsplit('/', 1)[-1], 'folder': {}}
        return None

    def handle(self, host, method, target, headers, body):
        self.requests.append((host, method, target))
        url = urlsplit(target)
        if host == 'login.microsoftonline.com':
            form = parse_qs(body or '')
            ok = (url.path == f'/{TENANT}/oauth2/v2.0/token' and form.get('client_id') == [CLIENT]
                  and form.get('client_secret') == [self.secret]
                  and form.get('scope') == ['https://graph.microsoft.com/.default'])
            return (200, {'token_type': 'Bearer', 'access_token': self.token}) if ok else \
                (401, {'error': 'invalid_client', 'error_description': 'AADSTS7000215 secret-value'})
        if host == 'contoso.sharepoint.com':
            query = parse_qs(url.query)
            drive, _, path = unquote(query['UniqueId'][0]).partition(':')
            if path in self.fail: return self.fail[path], b'failure mentioning secret-row-value'
            content = self.drives[drive].get(path)
            if content is None: return 404, b''
            return 200, content[:-1] if path in self.truncate else content
        if headers.get('Authorization') != 'Bearer ' + self.token:
            return 401, {'error': {'code': 'InvalidAuthenticationToken'}}
        path = unquote(url.path)
        if path == '/v1.0/sites/contoso.sharepoint.com:/sites/finance':
            return 200, {'id': SITE_ID}
        prefix = f'/v1.0/sites/{SITE_ID}/lists/'
        if path.startswith(prefix):
            name, _, rest = path[len(prefix):].partition('/')
            found = self.lists.get(name)
            if found is None: return 404, {'error': {'code': 'itemNotFound'}}
            if name in self.fail: return self.fail[name], {'error': {'message': 'secret-row-value'}}
            if rest == 'columns':
                return 200, {'value': [{'name': c, 'displayName': c} for c in found['columns']]}
            if rest == 'items':
                start = int(parse_qs(url.query).get('$skiptoken', ['0'])[0])
                items = found['items'][start:start + self.page_size]
                page = {'value': [{'id': str(start + i + 1), 'fields': dict(f)} for i, f in enumerate(items)]}
                if start + self.page_size < len(found['items']):
                    page['@odata.nextLink'] = (f'https://graph.microsoft.com{url.path}?$top=200'
                                               f'&$skiptoken={start + self.page_size}')
                return 200, page
        if path == f'/v1.0/sites/{SITE_ID}/drives':
            return 200, {'value': [{'id': 'drive-docs', 'name': 'Documents', 'driveType': 'documentLibrary',
                                    'webUrl': 'https://contoso.sharepoint.com/sites/finance/Shared%20Documents'}]}
        if path == '/v1.0/users/reader@contoso.example/drive':
            return 200, {'id': 'drive-user', 'driveType': 'business'}
        if path.startswith('/v1.0/drives/') and path.endswith('/children'):
            drive, _, folder = path.removeprefix('/v1.0/drives/').removesuffix('/children').partition('/items/')
            folder = folder.split(':', 1)[1]
            names = sorted({p[len(folder) + 1:].split('/', 1)[0] for p in self.drives[drive]
                            if p.startswith(folder + '/')})
            children = [self._item(drive, folder + '/' + n) for n in names]
            start = int(parse_qs(url.query).get('$skiptoken', ['0'])[0])
            page = {'value': children[start:start + self.page_size]}
            if start + self.page_size < len(children):
                page['@odata.nextLink'] = (f'https://graph.microsoft.com{url.path}?$top=200'
                                           f'&$skiptoken={start + self.page_size}')
            return 200, page
        if path.startswith('/v1.0/drives/') and '/root:/' in path:
            drive, _, rest = path.removeprefix('/v1.0/drives/').partition('/root:/')
            if rest in self.fail: return self.fail[rest], {'error': {'message': 'secret-row-value'}}
            item = self._item(drive, rest)
            return (200, item) if item else (404, {'error': {'code': 'itemNotFound'}})
        return 404, {'error': {'code': 'itemNotFound'}}

    def connection(self):
        api = self

        class Response:
            def __init__(self, status, body):
                self.status = status
                self.body = body if isinstance(body, bytes) else json.dumps(body).encode()

            def read(self, n=-1):
                chunk, self.body = (self.body, b'') if n < 0 else (self.body[:n], self.body[n:])
                return chunk

            def getheader(self, name, default=None):
                return str(len(self.body)) if name == 'Content-Length' else default

        class Connection:
            def __init__(self, host, timeout=None):
                assert host in ('login.microsoftonline.com', 'graph.microsoft.com', 'contoso.sharepoint.com'), host
                self.host = host

            def request(self, method, target, body=None, headers=None):
                self.response = Response(*api.handle(self.host, method, target, headers or {}, body))

            def getresponse(self):
                return self.response

            def close(self):
                pass
        return Connection
