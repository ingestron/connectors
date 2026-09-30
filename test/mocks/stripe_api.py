"""An in-memory Stripe list API for tests; never a runtime asset (PB-064 phase 4).

Follows Stripe's documented list behaviour: newest first, `limit` (1-100),
`starting_after` cursor, {"object": "list", "data": [...], "has_more": bool,
"url": "/v1/<object>"}, Bearer authentication, and error bodies of the form
{"error": {"type": ..., "message": ...}}.
"""
import json
from urllib.parse import parse_qs, urlsplit


class StripeApi:
    def __init__(self, key):
        self.key, self.objects, self.fail, self.requests = key, {}, {}, []

    def load(self, obj, rows):
        self.objects[obj] = list(rows)

    def handle(self, method, target, headers):
        """Return (status, body bytes) for one request."""
        self.requests.append((method, target))
        url = urlsplit(target)
        obj = url.path.removeprefix('/v1/')
        if headers.get('Authorization') != 'Bearer ' + self.key:
            return 401, _error('invalid_request_error', 'Invalid API Key provided: secret-value')
        if method != 'GET' or obj not in self.objects:
            return 404, _error('invalid_request_error', 'Unrecognized request URL')
        if obj in self.fail:
            return self.fail[obj], _error('api_error', 'failure mentioning secret-row-value')
        query = parse_qs(url.query)
        limit = int(query.get('limit', ['10'])[0])
        if not 1 <= limit <= 100:
            return 400, _error('invalid_request_error', 'Invalid limit')
        rows = self.objects[obj]
        start = 0
        if 'starting_after' in query:
            ids = [r.get('id') for r in rows]
            start = ids.index(query['starting_after'][0]) + 1
        page = rows[start:start + limit]
        return 200, json.dumps({'object': 'list', 'data': page,
                                'has_more': start + limit < len(rows), 'url': url.path}).encode()

    def connection(self):
        api = self

        class Response:
            def __init__(self, status, body):
                self.status, self.body = status, body

            def read(self, n=-1):
                chunk, self.body = (self.body, b'') if n < 0 else (self.body[:n], self.body[n:])
                return chunk

        class Connection:
            def __init__(self, host, timeout=None):
                assert host == 'api.stripe.com', host

            def request(self, method, target, headers=None):
                self.response = Response(*api.handle(method, target, headers or {}))

            def getresponse(self):
                return self.response

            def close(self):
                pass
        return Connection


def _error(kind, message):
    return json.dumps({'error': {'type': kind, 'message': message}}).encode()
