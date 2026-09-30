"""Amazon S3 and Google Cloud Storage objects over their S3-compatible APIs (PB-064 phase 7).

Requests are signed with AWS Signature Version 4 using the Python standard
library. S3 uses virtual-hosted endpoints (or path-style for a configured
S3-compatible endpoint); Google Cloud Storage uses its XML API at
storage.googleapis.com with HMAC keys and region `auto`. A path naming one
object reads it; a prefix reads every object of the selected format directly
under it, in key order, with one shared schema. Documented at
docs.aws.amazon.com/AmazonS3 and cloud.google.com/storage/docs/interoperability
(accessed 2026-10-01).
"""
import datetime
import hashlib
import hmac
import http.client
import re
import tempfile
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from urllib.parse import quote, urlsplit, urlencode

from files_reader import scan as scan_file, MAX_BYTES

MAX_FILES = 100
MAX_LIST = 4_000_000
EMPTY = hashlib.sha256(b'').hexdigest()
BUCKET = re.compile(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]')
REGION = re.compile(r'[a-z]{2}(-[a-z]+)+-\d|auto')
SUFFIX = {'csv': '.csv', 'tsv': '.tsv', 'json': '.json', 'jsonl': '.jsonl', 'parquet': '.parquet'}


def errors(prefix, label):
    return {
        prefix + '_AUTH': f'{label} rejected the access key or signature; check the key and clock.',
        prefix + '_FORBIDDEN': f'{label} denied access; grant read and list access to the bucket.',
        prefix + '_NOT_FOUND': f'The {label} bucket or path was not found.',
        prefix + '_RATE_LIMIT': f'{label} throttled the request; wait before retrying.',
        prefix + '_UNAVAILABLE': f'{label} is unavailable; retry later.',
        prefix + '_RESPONSE': f'{label} returned an unexpected response.',
        prefix + '_TOO_LARGE': 'An object exceeds 64 MiB or the prefix has more than 100 matching objects.',
        prefix + '_NO_FILES': 'The prefix has no objects of the selected format.',
        prefix + '_CHANGED': 'An object changed during download; retry when it is stable.',
        prefix + '_SCHEMA': 'Objects under the prefix have different columns; keep one schema per table.',
        prefix + '_NETWORK': f'Cannot reach {label}; check network access and retry.',
    }


class StoreError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, message):
    if not condition: raise ValueError(message)


def endpoint(settings, kind):
    """Return (scheme, host, path-style, region) for the connection."""
    bucket, region = settings.get('bucket', ''), settings.get('region', 'auto' if kind == 'gcs' else '')
    require(isinstance(bucket, str) and BUCKET.fullmatch(bucket) and '..' not in bucket, 'Use a bucket name')
    require(isinstance(region, str) and REGION.fullmatch(region), 'Use a region such as ap-southeast-2')
    for key in ('access_key_id', 'secret_access_key'):
        require(isinstance(settings.get(key), str) and 8 <= len(settings[key]) <= 256,
                'Set access_key_id and secret_access_key (a secret reference)')
    if kind == 'gcs':
        return 'https', 'storage.googleapis.com', True, 'auto'
    custom = settings.get('endpoint')
    if custom is None:
        return 'https', f'{bucket}.s3.{region}.amazonaws.com', False, region
    url = urlsplit(custom)
    loopback = url.hostname in ('127.0.0.1', 'localhost')
    require(url.scheme == 'https' or (url.scheme == 'http' and loopback),
            'endpoint must be https (http only for a loopback test server)')
    require(url.hostname and url.path in ('', '/') and not url.query, 'endpoint is a base URL only')
    return url.scheme, url.netloc, True, region


def table_path(path):
    require(isinstance(path, str) and 0 < len(path) <= 1024 and not path.startswith('/')
            and all(ord(c) >= 32 for c in path) and all(p not in ('', '.', '..') for p in path.split('/')),
            'path must be a relative object key or prefix without traversal')
    return path


def _sign(settings, region, method, host, path, query, now, payload=EMPTY):
    stamp, day = now.strftime('%Y%m%dT%H%M%SZ'), now.strftime('%Y%m%d')
    headers = {'host': host, 'x-amz-content-sha256': payload, 'x-amz-date': stamp}
    if settings.get('session_token'): headers['x-amz-security-token'] = settings['session_token']
    names = ';'.join(sorted(headers))
    canonical = '\n'.join([method, path, query,
                           ''.join(f'{k}:{headers[k]}\n' for k in sorted(headers)), names, payload])
    scope = f'{day}/{region}/s3/aws4_request'
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    to_sign = f'AWS4-HMAC-SHA256\n{stamp}\n{scope}\n{digest}'
    key = ('AWS4' + settings['secret_access_key']).encode()
    for part in (day, region, 's3', 'aws4_request'):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    headers['Authorization'] = (f"AWS4-HMAC-SHA256 Credential={settings['access_key_id']}/{scope}, "
                                f'SignedHeaders={names}, Signature={signature}')
    return headers


def request(prefix, settings, kind, method, key, query=None, limit=MAX_LIST, now=None):
    scheme, host, path_style, region = endpoint(settings, kind)
    bucket = settings['bucket']
    path = (f'/{bucket}/' if path_style else '/') + quote(key, safe='/~')
    if key == '': path = f'/{bucket}' if path_style else '/'
    canonical_query = '&'.join(f'{quote(k, safe="-_.~")}={quote(str(v), safe="-_.~")}'
                               for k, v in sorted((query or {}).items()))
    headers = _sign(settings, region, method, host, path, canonical_query,
                    now or datetime.datetime.now(datetime.timezone.utc))
    connection = None
    try:
        factory = http.client.HTTPSConnection if scheme == 'https' else http.client.HTTPConnection
        connection = factory(host, timeout=60)
        connection.request(method, path + ('?' + canonical_query if canonical_query else ''), headers=headers)
        response = connection.getresponse()
        status = response.status
        data = response.read(limit + 1)
        etag = response.getheader('ETag')
    except StoreError:
        raise
    except Exception:
        raise StoreError(prefix + '_NETWORK') from None
    finally:
        if connection is not None: connection.close()
    if status in (401, 403):
        raise StoreError(prefix + ('_FORBIDDEN' if b'AccessDenied' in data[:2000] else '_AUTH'))
    if status == 404: raise StoreError(prefix + '_NOT_FOUND')
    if status in (429, 503) and b'SlowDown' in data[:2000]: raise StoreError(prefix + '_RATE_LIMIT')
    if status >= 500: raise StoreError(prefix + '_UNAVAILABLE')
    if not 200 <= status < 300: raise StoreError(prefix + '_RESPONSE')
    if len(data) > limit: raise StoreError(prefix + '_TOO_LARGE')
    return data, etag


def objects(prefix, settings, kind, path, fmt):
    """The objects a table reads: the key itself, or matching objects directly under the prefix."""
    folder = path.rstrip('/') + '/'
    found, token, listed = [], None, False
    while True:
        query = {'list-type': '2', 'prefix': folder, 'delimiter': '/', **({'continuation-token': token} if token else {})}
        data, _ = request(prefix, settings, kind, 'GET', '', query)
        try:
            root = ElementTree.fromstring(data)
        except ElementTree.ParseError:
            raise StoreError(prefix + '_RESPONSE') from None
        ns = root.tag[:root.tag.index('}') + 1] if root.tag.startswith('{') else ''
        for item in root.findall(ns + 'Contents'):
            listed = True
            key, size = item.findtext(ns + 'Key'), item.findtext(ns + 'Size')
            if key and key.lower().endswith(SUFFIX[fmt]) and '/' not in key[len(folder):]:
                found.append((key, int(size or -1)))
        if len(found) > MAX_FILES: raise StoreError(prefix + '_TOO_LARGE')
        token = root.findtext(ns + 'NextContinuationToken')
        if root.findtext(ns + 'IsTruncated') != 'true' or not token: break
    if found: return sorted(found)
    if listed: raise StoreError(prefix + '_NO_FILES')
    return [(path, None)]


def scan(prefix, settings, kind, table, emit=None):
    items = objects(prefix, settings, kind, table['path'], table['format'])
    if emit is None: items = items[:1]
    schema = None
    with tempfile.TemporaryDirectory(prefix='ingestron-objects-') as folder:
        for index, (key, size) in enumerate(items):
            if size is not None and not 0 <= size <= MAX_BYTES: raise StoreError(prefix + '_TOO_LARGE')
            data, _ = request(prefix, settings, kind, 'GET', key, limit=MAX_BYTES)
            if size is not None and len(data) != size: raise StoreError(prefix + '_CHANGED')
            local = Path(folder).resolve() / f'input-{index}'
            local.write_bytes(data)
            current, _ = scan_file({'path': str(local), 'format': table['format'], 'types': table['types']}, emit)
            local.unlink()
            if schema is not None and current != schema: raise StoreError(prefix + '_SCHEMA')
            schema = current
    return schema
