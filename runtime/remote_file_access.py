"""Paged cloud file inventory; only list metadata, never download objects.

Uses S3/GCS ListObjectsV2 and Azure List Blobs. Prefixes are literal and
recursive. Each response consumes one bounded vendor page, so a filtered page
can be empty and still carry a continuation. Existing metadata/sample methods
retain their explicitly selected file behaviour.
"""
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qsl, quote, unquote, urlencode
from xml.etree import ElementTree

from source_access import AccessError, object_entry, secret
from remote_file_schema import execute as source_execute

FORMATS = ('csv', 'tsv', 'json', 'jsonl', 'parquet')
KINDS = ('s3', 'gcs', 'azure-blob')
MAX_BODY = 1_000_000
MAX_TOKEN = 2048
NAMESPACES = ('', 'http://s3.amazonaws.com/doc/2006-03-01/',
              'http://doc.s3.amazonaws.com/2006-03-01',
              'http://doc.s3.amazonaws.com/2006-03-01/')


def require(value, code='ACCESS_INPUT'):
    if not value:
        raise AccessError(code)


def safe_text(value, maximum, empty=False):
    return (isinstance(value, str) and (empty or bool(value))
            and len(value) <= maximum
            and all(ord(c) >= 32 and ord(c) != 127 for c in value))


def selectable_path(value):
    return (safe_text(value, 1024) and not value.startswith('/')
            and all(p not in ('', '.', '..') for p in value.split('/'))
            and len(value.rsplit('/', 1)[-1]) <= 300)


def cursor_identity(kind, settings, prefix, fmt, query):
    # Credential values are neither persisted nor included in cursors. A cursor
    # confers no access: every page uses this connection's current credentials.
    connection = {key: settings.get(key) for key in
                  ('bucket', 'region', 'endpoint', 'account', 'container')}
    return hashlib.sha256(json.dumps([kind, connection, prefix, fmt, query],
                                    sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def decode_cursor(value, identity):
    require(safe_text(value, 4000))
    try:
        require(re.fullmatch(r'[A-Za-z0-9_-]+', value))
        raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
        cursor = json.loads(raw)
        require(isinstance(cursor, dict) and set(cursor) == {'v', 'scope', 'token'})
        require(type(cursor['v']) is int and cursor['v'] == 1 and cursor['scope'] == identity)
        require(safe_text(cursor['token'], MAX_TOKEN))
        return cursor['token']
    except AccessError:
        raise
    except Exception:
        raise AccessError('ACCESS_INPUT') from None


def encode_cursor(token, identity):
    require(safe_text(token, MAX_TOKEN), 'ACCESS_RESPONSE')
    value = base64.urlsafe_b64encode(json.dumps(
        {'v': 1, 'scope': identity, 'token': token},
        separators=(',', ':'), ensure_ascii=False).encode()).decode().rstrip('=')
    require(len(value) <= 4000, 'ACCESS_TOO_LARGE')
    return value


def xml_root(body, expected):
    require(isinstance(body, bytes) and len(body) <= MAX_BODY, 'ACCESS_TOO_LARGE')
    # Reject declarations before parsing, including UTF-16/32 encodings. The
    # APIs use UTF-8; there is no need to accept external or internal entities.
    require(b'\x00' not in body and not re.search(br'<!\s*(DOCTYPE|ENTITY)', body, re.I), 'ACCESS_RESPONSE')
    try:
        root = ElementTree.fromstring(body)
    except Exception:
        raise AccessError('ACCESS_RESPONSE') from None
    namespace = root.tag[1:].split('}')[0] if root.tag.startswith('{') else ''
    require(namespace in (NAMESPACES if expected == 'ListBucketResult' else ('',)), 'ACCESS_RESPONSE')
    ns = '{' + namespace + '}' if namespace else ''
    require(root.tag == ns + expected, 'ACCESS_RESPONSE')
    return root, ns


def single(parent, name, required=True):
    nodes = parent.findall(name)
    require(len(nodes) == 1 if required else len(nodes) <= 1, 'ACCESS_RESPONSE')
    return nodes[0].text or '' if nodes else None


def store_page(kind, settings, prefix, limit, token):
    from object_store_reader import request
    query = {'list-type': '2', 'prefix': prefix, 'max-keys': limit, 'encoding-type': 'url'}
    if token:
        query['continuation-token'] = token
    body, _ = request(kind.upper(), settings, kind, 'GET', '', query, limit=MAX_BODY)
    root, ns = xml_root(body, 'ListBucketResult')
    encoding = single(root, ns + 'EncodingType', False)
    require(encoding in (None, 'url'), 'ACCESS_RESPONSE')
    items = root.findall(ns + 'Contents')
    require(len(items) <= limit, 'ACCESS_RESPONSE')
    found = []
    for item in items:
        key = single(item, ns + 'Key')
        if encoding == 'url':
            require(not re.search(r'%(?![0-9a-fA-F]{2})', key), 'ACCESS_RESPONSE')
            try:
                key = unquote(key, encoding='utf-8', errors='strict')
            except Exception:
                raise AccessError('ACCESS_RESPONSE') from None
        size = single(item, ns + 'Size')
        require(bool(re.fullmatch(r'[0-9]{1,20}', size)), 'ACCESS_RESPONSE')
        found.append((key, False))
    truncated = single(root, ns + 'IsTruncated')
    require(truncated in ('true', 'false'), 'ACCESS_RESPONSE')
    next_token = single(root, ns + 'NextContinuationToken', False)
    if truncated == 'true':
        require(safe_text(next_token, MAX_TOKEN) and next_token != token, 'ACCESS_RESPONSE')
    else:
        require(next_token in (None, ''), 'ACCESS_RESPONSE')
        next_token = None
    return found, next_token


def azure_page(settings, prefix, limit, token):
    from azure_blob_reader import endpoint
    from source_access import api
    host, container, sas = endpoint(settings)
    require('l' in dict(parse_qsl(sas))['sp'], 'ACCESS_FORBIDDEN')
    query = {'restype': 'container', 'comp': 'list', 'prefix': prefix, 'maxresults': limit}
    if token:
        query['marker'] = token
    body = api(host, '/' + container + '?' + sas + '&' + urlencode(query),
               {'x-ms-version': '2023-11-03'})
    root, _ = xml_root(body, 'EnumerationResults')
    nodes = root.findall('Blobs')
    require(len(nodes) == 1, 'ACCESS_RESPONSE')
    items = nodes[0].findall('Blob')
    require(len(items) <= limit and not nodes[0].findall('BlobPrefix'), 'ACCESS_RESPONSE')
    found = []
    for item in items:
        key = single(item, 'Name')
        name_node = item.find('Name')
        if name_node.get('Encoded') == 'true':
            require(not re.search(r'%(?![0-9a-fA-F]{2})', key), 'ACCESS_RESPONSE')
            try:
                key = unquote(key, encoding='utf-8', errors='strict')
            except Exception:
                raise AccessError('ACCESS_RESPONSE') from None
        properties = item.findall('Properties')
        require(len(properties) == 1, 'ACCESS_RESPONSE')
        size = single(properties[0], 'Content-Length')
        require(bool(re.fullmatch(r'[0-9]{1,20}', size)), 'ACCESS_RESPONSE')
        resource_type = single(properties[0], 'ResourceType', False)
        directory = resource_type == 'directory'
        found.append((key, directory))
    next_token = single(root, 'NextMarker')
    if next_token:
        require(safe_text(next_token, MAX_TOKEN) and next_token != token, 'ACCESS_RESPONSE')
    return found, next_token or None


def inventory(request):
    kind = request['connector']
    require(kind in KINDS)
    scope = request.get('scope', {})
    require(isinstance(scope, dict) and set(scope) <= {'prefix', 'format'})
    prefix, fmt = scope.get('prefix', ''), scope.get('format', 'all')
    require(safe_text(prefix, 1024, empty=True) and not prefix.startswith('/')
            and (not prefix or all(p not in ('', '.', '..') for p in (prefix[:-1] if prefix.endswith('/') else prefix).split('/'))))
    require(fmt in ('all', *FORMATS))
    query, limit = request.get('query', ''), request.get('limit', 50)
    require(safe_text(query, 128, empty=True) and type(limit) is int and 1 <= limit <= 200)
    require(not request.get('schema') and 'source' not in request and 'tables' not in request)
    settings = secret(request['settings'])
    identity = cursor_identity(kind, settings, prefix, fmt, query)
    token = decode_cursor(request['cursor'], identity) if request.get('cursor') else None
    found, next_token = (azure_page(settings, prefix, limit, token) if kind == 'azure-blob'
                         else store_page(kind, settings, prefix, limit, token))
    require(len({key for key, _ in found}) == len(found), 'ACCESS_RESPONSE')
    tables, omitted = [], False
    for key, directory in found:
        require(isinstance(key, str) and key.startswith(prefix), 'ACCESS_RESPONSE')
        extension = key.rsplit('.', 1)[-1].lower() if '.' in key else ''
        if directory or key.endswith('/') or extension not in FORMATS:
            continue
        if not selectable_path(key):
            omitted = True
            continue
        if (fmt != 'all' and extension != fmt) or query.casefold() not in key.casefold():
            continue
        tables.append(object_entry({'path': key, 'format': extension}, key.rsplit('/', 1)[-1], 'file'))
    result = {'apiVersion': 'ingestron.source-access-result/v1', 'action': 'inventory',
              'status': 'succeeded', 'scope': 'file', 'tables': tables}
    if next_token:
        result['nextCursor'] = encode_cursor(next_token, identity)
    if omitted:
        result['code'] = 'UNSUPPORTED_OBJECT_PATH'
    return result


def execute(request):
    if request.get('action') != 'inventory':
        return source_execute(request)
    result = {'apiVersion': 'ingestron.source-access-result/v1', 'action': 'inventory',
              'status': 'failed', 'scope': 'file', 'tables': []}
    try:
        return inventory(request)
    except Exception as error:
        code = getattr(error, 'code', 'ACCESS_FAILED')
        if not isinstance(code, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{2,40}', code):
            code = 'ACCESS_FAILED'
        result['code'] = code
    return result


if __name__ == '__main__':
    try:
        path = Path(sys.argv[1])
        require(path.stat().st_size <= 1_000_000, 'ACCESS_TOO_LARGE')
        result = execute(json.loads(path.read_text()))
    except Exception:
        result = {'apiVersion': 'ingestron.source-access-result/v1', 'action': 'inventory',
                  'status': 'failed', 'scope': 'file', 'tables': [], 'code': 'ACCESS_INPUT'}
    print(json.dumps(result))
