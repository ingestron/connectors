"""An in-memory S3-compatible API (S3 and GCS XML) for tests; never a runtime asset (PB-064 phase 7).

Implements ListObjectsV2 (prefix, delimiter, continuation tokens) and GetObject,
requires an AWS4-HMAC-SHA256 Authorization header for the configured key, and
returns S3-style XML error bodies.
"""
from urllib.parse import parse_qs, unquote, urlsplit

NS = 'http://s3.amazonaws.com/doc/2006-03-01/'


class S3Api:
    def __init__(self, access_key, host, bucket, path_style):
        self.access_key, self.host, self.bucket, self.path_style = access_key, host, bucket, path_style
        self.objects, self.fail, self.truncate, self.page_size, self.requests = {}, {}, set(), 2, []

    def handle(self, host, method, target, headers):
        self.requests.append((host, method, target))
        auth = headers.get('Authorization', '')
        if not auth.startswith(f'AWS4-HMAC-SHA256 Credential={self.access_key}/'):
            return 403, b'<Error><Code>SignatureDoesNotMatch</Code><Message>secret-value</Message></Error>'
        url = urlsplit(target)
        path = unquote(url.path)
        if self.path_style:
            if not path.startswith(f'/{self.bucket}'): return 404, b'<Error><Code>NoSuchBucket</Code></Error>'
            path = path[len(self.bucket) + 1:]
        key = path.lstrip('/')
        if key == '':
            query = parse_qs(url.query)
            prefix = query.get('prefix', [''])[0]
            keys = sorted(k for k in self.objects if k.startswith(prefix)
                          and '/' not in k[len(prefix):])
            start = int(query.get('continuation-token', ['0'])[0])
            page = keys[start:start + self.page_size]
            more = start + self.page_size < len(keys)
            body = ''.join(f'<Contents><Key>{k}</Key><Size>{len(self.objects[k])}</Size></Contents>' for k in page)
            body += f'<IsTruncated>{"true" if more else "false"}</IsTruncated>'
            if more: body += f'<NextContinuationToken>{start + self.page_size}</NextContinuationToken>'
            return 200, f'<ListBucketResult xmlns="{NS}">{body}</ListBucketResult>'.encode()
        if key in self.fail: return self.fail[key], b'<Error><Code>InternalError</Code><Message>secret-row-value</Message></Error>'
        if key not in self.objects: return 404, b'<Error><Code>NoSuchKey</Code></Error>'
        data = self.objects[key]
        return 200, data[:-1] if key in self.truncate else data

    def connection(self):
        api = self

        class Response:
            def __init__(self, status, body):
                self.status, self.body = status, body

            def read(self, n=-1):
                chunk, self.body = (self.body, b'') if n < 0 else (self.body[:n], self.body[n:])
                return chunk

            def getheader(self, name, default=None):
                return default

        class Connection:
            def __init__(self, host, timeout=None):
                assert host == api.host, host

            def request(self, method, target, body=None, headers=None):
                self.response = Response(*api.handle(api.host, method, target, headers or {}))

            def getresponse(self):
                return self.response

            def close(self):
                pass
        return Connection
