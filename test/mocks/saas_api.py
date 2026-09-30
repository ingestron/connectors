"""In-memory Salesforce, HubSpot and Jira APIs for tests; never runtime assets (PB-064 phase 7).

Each follows the vendor's documented request and response shapes for the calls
the connectors make, including authentication, paging and error status codes.
"""
import base64
import json
from urllib.parse import parse_qs, unquote, urlsplit


class Base:
    host = ''

    def __init__(self):
        self.requests, self.fail, self.page_size = [], {}, 2

    def connection(self):
        api = self

        class Response:
            def __init__(self, status, body):
                self.status = status
                self.body = body if isinstance(body, bytes) else json.dumps(body).encode()

            def read(self, n=-1):
                chunk, self.body = (self.body, b'') if n < 0 else (self.body[:n], self.body[n:])
                return chunk

        class Connection:
            def __init__(self, host, timeout=None):
                self.host = host

            def request(self, method, target, body=None, headers=None):
                api.requests.append((self.host, method, target))
                self.response = Response(*api.handle(self.host, method, target, headers or {}, body))

            def getresponse(self):
                return self.response

            def close(self):
                pass
        return Connection


class SalesforceApi(Base):
    """OAuth client credentials, sobject describe and SOQL query with nextRecordsUrl."""
    host = 'acme.my.salesforce.com'

    def __init__(self, client_id, secret):
        super().__init__()
        self.client_id, self.secret, self.objects = client_id, secret, {}

    def load(self, obj, fields, rows):
        self.objects[obj] = {'fields': fields, 'rows': list(rows)}

    def handle(self, host, method, target, headers, body):
        url = urlsplit(target)
        if host != self.host: return 404, b''
        if url.path == '/services/oauth2/token':
            form = parse_qs(body or '')
            ok = form.get('client_id') == [self.client_id] and form.get('client_secret') == [self.secret]
            return (200, {'access_token': 'sf-access', 'instance_url': 'https://' + self.host}) if ok else \
                (400, {'error': 'invalid_client', 'error_description': 'secret-value rejected'})
        if headers.get('Authorization') != 'Bearer sf-access':
            return 401, [{'errorCode': 'INVALID_SESSION_ID'}]
        parts = url.path.split('/')
        if url.path.endswith('/describe'):
            obj = parts[-2]
            if obj not in self.objects: return 404, [{'errorCode': 'NOT_FOUND'}]
            return 200, {'name': obj, 'fields': [{'name': n, 'type': t, 'nillable': True}
                                                  for n, t in self.objects[obj]['fields'].items()]}
        if parts[-1] == 'query' or '/query/' in url.path:
            if parts[-1] == 'query':
                soql = parse_qs(url.query)['q'][0]
                obj = soql.rsplit(' FROM ', 1)[1]
                start = 0
            else:
                obj, start = parts[-1].split('-')
                start = int(start)
            if obj in self.fail: return self.fail[obj], [{'errorCode': 'SERVER_ERROR', 'message': 'secret-row-value'}]
            rows = self.objects[obj]['rows']
            page = rows[start:start + self.page_size]
            done = start + self.page_size >= len(rows)
            result = {'totalSize': len(rows), 'done': done,
                      'records': [{'attributes': {'type': obj}, **r} for r in page]}
            if not done: result['nextRecordsUrl'] = f'/services/data/v62.0/query/{obj}-{start + self.page_size}'
            return 200, result
        return 404, [{'errorCode': 'NOT_FOUND'}]


class HubSpotApi(Base):
    """Private app bearer token, CRM v3 properties and objects with paging.next.after."""
    host = 'api.hubapi.com'

    def __init__(self, token):
        super().__init__()
        self.token, self.objects = token, {}

    def load(self, obj, props, rows):
        self.objects[obj] = {'props': props, 'rows': list(rows)}

    def handle(self, host, method, target, headers, body):
        url = urlsplit(target)
        if headers.get('Authorization') != 'Bearer ' + self.token:
            return 401, {'status': 'error', 'category': 'INVALID_AUTHENTICATION'}
        parts = url.path.split('/')
        obj = parts[-1]
        if obj not in self.objects: return 404, {'status': 'error', 'category': 'OBJECT_NOT_FOUND'}
        if obj in self.fail: return self.fail[obj], {'status': 'error', 'message': 'secret-row-value'}
        if url.path.startswith('/crm/v3/properties/'):
            return 200, {'results': [{'name': n, 'type': t} for n, t in self.objects[obj]['props'].items()]}
        query = parse_qs(url.query)
        wanted = query.get('properties', [''])[0].split(',') if 'properties' in query else []
        start = int(query.get('after', ['0'])[0])
        rows = self.objects[obj]['rows']
        page = {'results': [{'id': r['id'], 'createdAt': r.get('createdAt'), 'updatedAt': r.get('updatedAt'),
                             'archived': False,
                             'properties': {k: r.get(k) for k in wanted}}
                            for r in rows[start:start + self.page_size]]}
        if start + self.page_size < len(rows):
            page['paging'] = {'next': {'after': str(start + self.page_size), 'link': 'https://api.hubapi.com/x'}}
        return 200, page


class JiraApi(Base):
    """Basic auth, /field, enhanced JQL search with nextPageToken, and startAt paging."""
    host = 'acme.atlassian.net'

    def __init__(self, email, token):
        super().__init__()
        self.auth = 'Basic ' + base64.b64encode(f'{email}:{token}'.encode()).decode()
        self.fields, self.issues, self.tables, self.repeat, self.searches = [], [], {}, False, []

    def handle(self, host, method, target, headers, body):
        url = urlsplit(target)
        if headers.get('Authorization') != self.auth:
            return 401, {'errorMessages': ['Client must be authenticated']}
        if url.path == '/rest/api/3/field':
            return 200, self.fields
        if url.path == '/rest/api/3/search/jql':
            if 'issues' in self.fail: return self.fail['issues'], {'errorMessages': ['secret-row-value']}
            request = json.loads(body)
            self.searches.append(request)
            if 'ORDER BY' not in request['jql'] and 'project' not in request['jql']:
                return 400, {'errorMessages': ['Unbounded JQL queries are not allowed here.']}
            start = 0 if self.repeat else int(request.get('nextPageToken') or 0)
            page = self.issues[start:start + self.page_size]
            result = {'issues': [{'id': i['id'], 'key': i['key'],
                                  'fields': {f: i['fields'].get(f) for f in request['fields']}} for i in page]}
            if start + self.page_size < len(self.issues):
                result['nextPageToken'] = 'x' if self.repeat else str(start + self.page_size)
            else:
                result['isLast'] = True
            return 200, result
        for name, (path, paged, rows) in self.tables.items():
            if url.path == path:
                if name in self.fail: return self.fail[name], {'errorMessages': ['secret-row-value']}
                if not paged: return 200, rows
                query = parse_qs(url.query)
                start, size = int(query['startAt'][0]), min(int(query['maxResults'][0]), self.page_size)
                chunk = rows[start:start + size]
                return 200, {'startAt': start, 'maxResults': size, 'total': len(rows),
                             'isLast': start + size >= len(rows), 'values': chunk}
        return 404, {'errorMessages': ['Not found']}
