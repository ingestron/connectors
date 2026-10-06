"""Read-only SFTP folder and Microsoft Graph file/list inventory.

SFTP takes bounded directory metadata and exposes sorted keyset pages. Graph
uses one native collection page with a scoped continuation restricted to that
collection. Neither inventory downloads file content or list item records.
"""
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote, unquote, urlencode, urlsplit, parse_qsl
from source_access import AccessError, object_entry, secret
from remote_file_schema import execute as source_execute

FORMATS = ('csv', 'tsv', 'json', 'jsonl', 'parquet')
MAX_ENTRIES = 10000
MAX_BYTES = 1_000_000


def require(value, code='ACCESS_INPUT'):
    if not value:
        raise AccessError(code)


def text(value, maximum, empty=False):
    return (isinstance(value, str) and (empty or bool(value)) and len(value) <= maximum
            and all(ord(c) >= 32 and ord(c) != 127 for c in value))


def path_value(value, kind, empty=False):
    require(text(value, 1024, empty=empty))
    if not value:
        return value
    if kind == 'sftp':
        require(not any(c in value for c in '"\\*?[]') and not value.startswith('//'))
        if value == '/':
            return value
        pieces = value.lstrip('/').split('/')
    else:
        require(not value.startswith('/') and not any(c in value for c in '\\:%'))
        pieces = value.split('/')
    require(all(p not in ('', '.', '..') for p in pieces))
    return value


def identity(kind, settings, scope, query, collection=None):
    connection = {key: settings.get(key) for key in
                  ('host', 'port', 'user', 'host_key', 'tenant_id', 'client_id', 'site')}
    return hashlib.sha256(json.dumps([kind, connection, scope, query, collection],
                                    sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def encode_cursor(scope, token):
    require(text(token, 2048), 'ACCESS_RESPONSE')
    cursor = base64.urlsafe_b64encode(json.dumps({'v':1, 'scope':scope, 'token':token},
                                             separators=(',', ':'), ensure_ascii=False).encode()).decode().rstrip('=')
    require(len(cursor) <= 4000, 'ACCESS_TOO_LARGE')
    return cursor


def decode_cursor(value, scope):
    require(text(value, 4000) and re.fullmatch(r'[A-Za-z0-9_-]+', value))
    try:
        cursor = json.loads(base64.b64decode(value + '='*(-len(value)%4), altchars=b'-_', validate=True))
        require(isinstance(cursor, dict) and set(cursor) == {'v','scope','token'})
        require(type(cursor['v']) is int and cursor['v'] == 1 and cursor['scope'] == scope)
        require(text(cursor['token'], 2048))
        return cursor['token']
    except AccessError:
        raise
    except Exception:
        raise AccessError('ACCESS_INPUT') from None


def sftp_inventory(settings, scope, query, limit, cursor):
    from sftp_reader import OpenSsh
    folder = path_value(scope.get('directory'), 'sftp')
    binding = identity('sftp', settings, scope, query)
    token = decode_cursor(cursor, binding) if cursor else None
    if token:
        try:
            previous = json.loads(token)
        except Exception:
            raise AccessError('ACCESS_INPUT') from None
        require(isinstance(previous, dict) and set(previous) == {'stamp', 'after'})
        require(text(previous['after'],300) and re.fullmatch('[a-f0-9]{64}', previous['stamp']))
    # cd requires an actual directory. -a includes hidden files; -n avoids user
    # name lookup. Paths cannot contain glob or batch-command delimiters.
    out = OpenSsh(settings).run([f'cd "{folder}"', 'ls -lan'], output_limit=MAX_BYTES, timeout=60)
    require(isinstance(out, str) and len(out.encode()) <= MAX_BYTES, 'ACCESS_TOO_LARGE')
    entries = []
    for line in out.splitlines():
        if not line.strip() or line.startswith('sftp>'):
            continue
        fields = line.split(None, 8)
        require(len(fields) == 9 and re.fullmatch(r'[-dlbcps][rwxstST-]{9}', fields[0])
                and fields[4].isdigit(), 'ACCESS_RESPONSE')
        name = fields[8]
        if name in ('.','..') or not fields[0].startswith('-'):
            continue
        require(text(name, 1024) and '/' not in name, 'ACCESS_RESPONSE')
        entries.append((name, int(fields[4]), fields[5:8]))
        require(len(entries) <= MAX_ENTRIES, 'ACCESS_TOO_LARGE')
    entries.sort()
    require(len({name for name, _, _ in entries}) == len(entries), 'ACCESS_RESPONSE')
    stamp = hashlib.sha256(json.dumps(entries, separators=(',', ':')).encode()).hexdigest()
    if token:
        require(previous['stamp'] == stamp, 'ACCESS_CHANGED')
    selected, omitted = [], False
    for name, _, _ in entries:
        extension = name.rsplit('.',1)[-1].lower() if '.' in name else ''
        if extension not in FORMATS or scope.get('format','all') not in ('all', extension) or query.casefold() not in name.casefold():
            continue
        if len(name) > 300 or any(c in name for c in '"\\*?[]'):
            omitted = True
            continue
        if token and name <= previous['after']:
            continue
        remote = folder.rstrip('/') + '/' + name
        if len(remote) > 1024:
            omitted = True
            continue
        selected.append(object_entry({'path':remote, 'format':extension}, name, 'file'))
    next_cursor = None
    if len(selected) > limit:
        next_cursor = encode_cursor(binding, json.dumps({'stamp':stamp, 'after':selected[limit-1]['name']}, separators=(',', ':')))
    return selected[:limit], next_cursor, omitted


def graph_id(value):
    require(text(value, 512) and not any(c in value for c in '/\\?#%'), 'ACCESS_RESPONSE')
    return quote(value, safe='')


def graph_next(value, collection, current):
    require(text(value, 2048), 'ACCESS_RESPONSE')
    url = urlsplit(value)
    require(url.scheme == 'https' and url.netloc == 'graph.microsoft.com' and not url.fragment
            and unquote(url.path) == unquote(collection), 'ACCESS_RESPONSE')
    pairs = parse_qsl(url.query, keep_blank_values=True)
    allowed = {'$skiptoken', '$skipToken', '$top', '$select', '$orderby'}
    require(pairs and len(dict(pairs)) == len(pairs) and all(k in allowed for k,_ in pairs), 'ACCESS_RESPONSE')
    require(any(k in ('$skiptoken','$skipToken') and v for k,v in pairs), 'ACCESS_RESPONSE')
    target = url.path + '?' + url.query
    require(target != current, 'ACCESS_RESPONSE')
    return target


def graph_library(access, site_id, host, library):
    from graph_reader import library_drive
    return graph_id(library_drive(access, unquote(site_id), host, library))


def graph_inventory(kind, settings, scope, query, limit, cursor):
    from graph_reader import settings_for, token, graph
    locator = settings_for(settings, kind)
    binding = identity(kind, settings, scope, query)
    continuation = decode_cursor(cursor, binding) if cursor else None
    access = token(settings)
    entity = scope.get('entity','file')
    if kind == 'sharepoint':
        _, host, site_name = locator
        site = graph(access, f'/v1.0/sites/{host}:/sites/{quote(site_name, safe="")}')
        site_id = graph_id(site.get('id'))
    if entity == 'list':
        require(kind == 'sharepoint' and not scope.get('directory') and scope.get('format','all') == 'all')
        collection = f'/v1.0/sites/{site_id}/lists'
        selected_fields = 'id,name,displayName,list'
        directory = ''
    else:
        directory = path_value(scope.get('directory',''), kind, empty=True)
        if kind == 'onedrive':
            drive = graph(access, f'/v1.0/users/{quote(locator[1], safe="@")}/drive')
            drive_id, path = graph_id(drive.get('id')), directory
        else:
            library, _, path = directory.partition('/')
            require(bool(library), 'SOURCE_PATH_REQUIRED')
            drive_id = graph_library(access, site_id, host, library)
        if path:
            folder = graph(access, f'/v1.0/drives/{drive_id}/root:/{quote(path, safe="/")}?$select=id,folder')
            require(isinstance(folder.get('folder'),dict), 'ACCESS_INPUT')
            collection = f'/v1.0/drives/{drive_id}/items/{graph_id(folder.get("id"))}/children'
        else:
            collection = f'/v1.0/drives/{drive_id}/root/children'
        selected_fields = 'id,name,size,file,folder'
    target = collection + '?' + urlencode({'$top':limit, '$select':selected_fields})
    if continuation:
        target = graph_next('https://graph.microsoft.com' + continuation, collection, target)
    page = graph(access, target)
    values = page.get('value')
    require(isinstance(values,list) and len(values) <= limit, 'ACCESS_RESPONSE')
    tables, names, omitted = [], set(), False
    for item in values:
        require(isinstance(item,dict) and text(item.get('name'),300), 'ACCESS_RESPONSE')
        name = item['name']
        require(name not in names, 'ACCESS_RESPONSE'); names.add(name)
        if entity == 'list':
            if not isinstance(item.get('list'),dict) or item['list'].get('template') == 'documentLibrary':
                continue
            if any(c in name for c in '/\\:%') or name in ('.','..'):
                omitted = True; continue
            require(text(item.get('id'),36) and re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', item['id']), 'ACCESS_RESPONSE')
            label = item.get('displayName', name)
            require(text(label,300), 'ACCESS_RESPONSE')
            if query.casefold() in name.casefold() or query.casefold() in label.casefold():
                tables.append(object_entry({'entity':'list','path':'Lists/'+item['id']}, label, 'object'))
        else:
            if not isinstance(item.get('file'),dict) or 'folder' in item:
                continue
            require(type(item.get('size')) is int and item['size'] >= 0, 'ACCESS_RESPONSE')
            extension = name.rsplit('.',1)[-1].lower() if '.' in name else ''
            if extension not in FORMATS or scope.get('format','all') not in ('all',extension) or query.casefold() not in name.casefold():
                continue
            remote = (directory + '/' if directory else '') + name
            if any(c in name for c in '/\\:%') or name in ('.','..') or len(remote) > 1024:
                omitted = True; continue
            tables.append(object_entry({'path':remote,'format':extension}, name, 'file'))
    nxt = page.get('@odata.nextLink')
    next_cursor = encode_cursor(binding, graph_next(nxt, collection, target)) if nxt is not None else None
    return tables, next_cursor, omitted


def inventory(request):
    kind = request['connector']
    require(kind in ('sftp','sharepoint','onedrive'))
    scope = request.get('scope',{})
    require(isinstance(scope,dict) and set(scope) <= ({'directory','format','entity'} if kind == 'sharepoint' else {'directory','format'}))
    scope = {'directory':scope.get('directory',''), 'format':scope.get('format','all'),
             **({'entity':scope.get('entity','file')} if kind == 'sharepoint' else {})}
    require(scope['format'] in ('all', *FORMATS))
    if kind == 'sharepoint':
        require(scope['entity'] in ('file','list'))
        require(scope['entity'] != 'list' or not scope['directory'] and scope['format'] == 'all')
        require(scope['entity'] != 'file' or bool(scope['directory']), 'SOURCE_PATH_REQUIRED')
    path_value(scope['directory'], kind, empty=kind != 'sftp')
    query, limit = request.get('query',''), request.get('limit',50)
    require(text(query,128,empty=True) and type(limit) is int and 1 <= limit <= 200)
    require(not request.get('schema') and 'source' not in request and 'tables' not in request)
    settings = secret(request['settings'])
    cursor = request.get('cursor')
    tables, nxt, omitted = (sftp_inventory(settings,scope,query,limit,cursor) if kind == 'sftp'
                            else graph_inventory(kind,settings,scope,query,limit,cursor))
    result = {'apiVersion':'ingestron.source-access-result/v1','action':'inventory',
              'status':'succeeded','scope':'file' if scope.get('entity') != 'list' else 'metadata','tables':tables}
    if nxt: result['nextCursor'] = nxt
    if omitted: result['code'] = 'UNSUPPORTED_OBJECT_PATH'
    return result


def execute(request):
    if request.get('action') != 'inventory':
        return source_execute(request)
    result = {'apiVersion':'ingestron.source-access-result/v1','action':'inventory',
              'status':'failed','scope':'metadata','tables':[]}
    try:
        return inventory(request)
    except Exception as error:
        code = getattr(error,'code','ACCESS_FAILED')
        result['code'] = code if isinstance(code,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{2,40}',code) else 'ACCESS_FAILED'
    return result


if __name__ == '__main__':
    try:
        path = Path(sys.argv[1]); require(path.stat().st_size <= MAX_BYTES, 'ACCESS_TOO_LARGE')
        result = execute(json.loads(path.read_text()))
    except Exception:
        result = {'apiVersion':'ingestron.source-access-result/v1','action':'inventory',
                  'status':'failed','scope':'metadata','tables':[],'code':'ACCESS_INPUT'}
    print(json.dumps(result))
