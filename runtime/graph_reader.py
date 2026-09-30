"""SharePoint and OneDrive files through Microsoft Graph (PB-064 phase 4).

App-only client credentials (POST login.microsoftonline.com/<tenant>/oauth2/v2.0/token
with scope https://graph.microsoft.com/.default), then Graph v1.0: resolve the
site's document library or the user's OneDrive, resolve the item by path, and
download each file through its pre-authenticated download URL. A file path reads
one file; a folder path reads every file of the selected format directly inside
it, in name order, and all must share one schema. A SharePoint list
(`Lists/<name>` with entity list) is read through the list items API with the
contract's fields. Public cloud only. Documented at learn.microsoft.com/graph
(accessed 2026-10-01).
"""
import http.client
import json
from decimal import Decimal
import re
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote, urlencode, urlsplit

from files_reader import scan as scan_file, MAX_BYTES

LOGIN = 'login.microsoftonline.com'
GRAPH = 'graph.microsoft.com'
MAX_RESPONSE = 4_000_000
MAX_FILES = 100
GUID = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
SITE = re.compile(r'https://([a-z0-9-]+\.sharepoint\.com)/sites/([A-Za-z0-9_.-]{1,128})')
USER = re.compile(r'[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}|' + GUID.pattern)
SUFFIX = {'csv': '.csv', 'tsv': '.tsv', 'json': '.json', 'jsonl': '.jsonl', 'parquet': '.parquet'}

ERRORS = {
    'GRAPH_AUTH': 'Microsoft Entra rejected the client credentials; check tenant, client ID and secret.',
    'GRAPH_FORBIDDEN': 'Microsoft Graph denied access; grant the app read access to this site or drive.',
    'GRAPH_NOT_FOUND': 'The site, library, drive or path was not found; check the connection and table path.',
    'GRAPH_RATE_LIMIT': 'Microsoft Graph throttled the request; wait before retrying.',
    'GRAPH_UNAVAILABLE': 'Microsoft Graph is unavailable; retry later.',
    'GRAPH_RESPONSE': 'Microsoft Graph returned an unexpected response.',
    'GRAPH_TOO_LARGE': 'A file exceeds 64 MiB or the folder has more than 100 matching files.',
    'GRAPH_NO_FILES': 'The folder has no files of the selected format.',
    'GRAPH_CHANGED': 'A file changed during download; retry when it is stable.',
    'GRAPH_SCHEMA': 'Files in the folder have different columns; keep one schema per table.',
    'GRAPH_NETWORK': 'Cannot reach Microsoft Graph; check network access and retry.',
}


class GraphError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, message):
    if not condition: raise ValueError(message)


def settings_for(settings, kind):
    """Validate a connection; returns the drive locator."""
    require(isinstance(settings.get('tenant_id'), str) and GUID.fullmatch(settings['tenant_id']),
            'tenant_id must be the directory (tenant) ID')
    require(isinstance(settings.get('client_id'), str) and GUID.fullmatch(settings['client_id']),
            'client_id must be the application (client) ID')
    secret = settings.get('client_secret')
    require(isinstance(secret, str) and 0 < len(secret) <= 1024,
            'Set client_secret through its secret reference')
    if kind == 'sharepoint':
        site = SITE.fullmatch(settings.get('site') or '')
        require(site, 'site must be https://<tenant>.sharepoint.com/sites/<name>')
        return ('site', site.group(1), site.group(2))
    user = settings.get('user')
    require(isinstance(user, str) and USER.fullmatch(user), 'user must be a user principal name or object ID')
    return ('user', user)


def table_path(path, kind):
    require(isinstance(path, str) and 0 < len(path) <= 1024 and not path.startswith('/')
            and not path.endswith('/') and all(ord(c) >= 32 for c in path)
            and all(p not in ('', '.', '..') for p in path.split('/')),
            'path must be a relative file or folder path without traversal')
    require(kind != 'sharepoint' or '/' in path,
            'SharePoint paths start with the document library, such as Shared Documents/<folder>')
    return path


def request(host, method, target, headers=None, body=None, limit=MAX_RESPONSE):
    """One HTTPS request; no redirects followed, bodies capped, errors never echoed."""
    connection = None
    try:
        connection = http.client.HTTPSConnection(host, timeout=30)
        connection.request(method, target, body=body, headers=headers or {})
        response = connection.getresponse()
        status = response.status
        data = response.read(limit + 1)
        length = response.getheader('Content-Length')
    except GraphError:
        raise
    except Exception:
        raise GraphError('GRAPH_NETWORK') from None
    finally:
        if connection is not None: connection.close()
    if len(data) > limit: raise GraphError('GRAPH_TOO_LARGE')
    return status, data, length


def _check(status, auth=False):
    if 200 <= status < 300: return
    if status in (400, 401) and auth: raise GraphError('GRAPH_AUTH')
    if status == 401: raise GraphError('GRAPH_AUTH')
    if status == 403: raise GraphError('GRAPH_FORBIDDEN')
    if status == 404: raise GraphError('GRAPH_NOT_FOUND')
    if status == 429: raise GraphError('GRAPH_RATE_LIMIT')
    if status >= 500: raise GraphError('GRAPH_UNAVAILABLE')
    raise GraphError('GRAPH_RESPONSE')


def _json(data):
    try:
        value = json.loads(data)
    except ValueError:
        raise GraphError('GRAPH_RESPONSE') from None
    if not isinstance(value, dict): raise GraphError('GRAPH_RESPONSE')
    return value


def token(settings):
    body = urlencode({'grant_type': 'client_credentials', 'client_id': settings['client_id'],
                      'client_secret': settings['client_secret'],
                      'scope': 'https://graph.microsoft.com/.default'})
    status, data, _ = request(LOGIN, 'POST', f"/{settings['tenant_id']}/oauth2/v2.0/token",
                              {'Content-Type': 'application/x-www-form-urlencoded'}, body)
    _check(status, auth=True)
    value = _json(data).get('access_token')
    if not isinstance(value, str) or not value: raise GraphError('GRAPH_RESPONSE')
    return value


def graph(access, target):
    status, data, _ = request(GRAPH, 'GET', target, {'Authorization': 'Bearer ' + access})
    _check(status)
    return _json(data)


def drive(access, locator, path):
    """Return (drive id, path inside the drive)."""
    if locator[0] == 'user':
        return str(graph(access, f"/v1.0/users/{quote(locator[1], safe='@')}/drive").get('id')), path
    _, host, name = locator
    site = graph(access, f'/v1.0/sites/{host}:/sites/{quote(name)}')
    library, _, rest = path.partition('/')
    require(rest, 'SharePoint paths start with the document library, such as Shared Documents/<folder>')
    drives = graph(access, f"/v1.0/sites/{quote(str(site.get('id')), safe=',.')}/drives").get('value')
    if not isinstance(drives, list): raise GraphError('GRAPH_RESPONSE')
    for entry in drives:
        url = entry.get('webUrl') if isinstance(entry, dict) else None
        if isinstance(url, str) and unquote(urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]) == unquote(library):
            return str(entry.get('id')), rest
    raise GraphError('GRAPH_NOT_FOUND')


def files(access, drive_id, path, fmt):
    item = graph(access, f"/v1.0/drives/{quote(drive_id)}/root:/{quote(unquote(path))}")
    if 'file' in item:
        return [item]
    if 'folder' not in item: raise GraphError('GRAPH_RESPONSE')
    found, target = [], f"/v1.0/drives/{quote(drive_id)}/items/{quote(str(item.get('id')))}/children?$top=200"
    while target:
        page = graph(access, target)
        values = page.get('value')
        if not isinstance(values, list): raise GraphError('GRAPH_RESPONSE')
        found += [v for v in values if isinstance(v, dict) and 'file' in v
                  and str(v.get('name', '')).lower().endswith(SUFFIX[fmt])]
        if len(found) > MAX_FILES: raise GraphError('GRAPH_TOO_LARGE')
        nxt = page.get('@odata.nextLink')
        if nxt is None: break
        url = urlsplit(nxt) if isinstance(nxt, str) else None
        if not (url and url.scheme == 'https' and url.hostname == GRAPH): raise GraphError('GRAPH_RESPONSE')
        target = url.path + ('?' + url.query if url.query else '')
    if not found: raise GraphError('GRAPH_NO_FILES')
    return sorted(found, key=lambda v: str(v.get('name')))


def download(item, destination):
    size = item.get('size')
    if not (isinstance(size, int) and 0 <= size <= MAX_BYTES): raise GraphError('GRAPH_TOO_LARGE')
    url = urlsplit(str(item.get('@microsoft.graph.downloadUrl', '')))
    # Pre-authenticated URLs point at the tenant's SharePoint host; nothing else is followed.
    if not (url.scheme == 'https' and url.hostname and url.hostname.endswith('.sharepoint.com')):
        raise GraphError('GRAPH_RESPONSE')
    status, data, _ = request(url.hostname, 'GET', url.path + ('?' + url.query if url.query else ''),
                              limit=MAX_BYTES)
    _check(status)
    if len(data) != size: raise GraphError('GRAPH_CHANGED')
    destination.write_bytes(data)


def list_name(path):
    name = path[len('Lists/'):] if path.startswith('Lists/') else ''
    require(name and '/' not in name and len(name) <= 255, 'A list path is Lists/<name>')
    return unquote(name)


def _value(value, kind):
    """Convert one list field to the contract type; lookups and people become JSON text."""
    if value is None: return None
    if kind == 'boolean':
        if isinstance(value, bool): return value
        raise GraphError('GRAPH_SCHEMA')
    if kind in ('integer', 'number', 'decimal'):
        if isinstance(value, bool) or not isinstance(value, (int, float, str)): raise GraphError('GRAPH_SCHEMA')
        try:
            number = Decimal(str(value))
        except ArithmeticError:
            raise GraphError('GRAPH_SCHEMA') from None
        if kind == 'integer':
            if number != number.to_integral_value(): raise GraphError('GRAPH_SCHEMA')
            return int(number)
        return number
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True, separators=(',', ':'))


def scan_list(access, locator, table, emit=None):
    """Read a SharePoint list's items; selected fields must exist as list columns."""
    _, host, name = locator
    site = graph(access, f'/v1.0/sites/{host}:/sites/{quote(name)}')
    base = f"/v1.0/sites/{quote(str(site.get('id')), safe=',.')}/lists/{quote(list_name(table['path']))}"
    columns = graph(access, base + '/columns').get('value')
    if not isinstance(columns, list): raise GraphError('GRAPH_RESPONSE')
    available = {c.get('name') for c in columns if isinstance(c, dict)}
    selected = table['types']
    if not set(selected) <= available: raise GraphError('GRAPH_SCHEMA')
    mapping = {'string': 'string', 'integer': 'integer', 'boolean': 'boolean', 'number': 'number', 'decimal': 'number'}
    schema = {'type': 'object', 'additionalProperties': False,
              'properties': {c: {'type': ['null', mapping[k]]} for c, k in sorted(selected.items())}}
    if emit is None: return schema
    target, count = base + '/items?expand=fields(select=' + ','.join(sorted(selected)) + ')&$top=200', 0
    while target:
        page = graph(access, target)
        items = page.get('value')
        if not isinstance(items, list): raise GraphError('GRAPH_RESPONSE')
        for item in items:
            fields = item.get('fields') if isinstance(item, dict) else None
            if not isinstance(fields, dict): raise GraphError('GRAPH_RESPONSE')
            emit({c: _value(fields.get(c), k) for c, k in sorted(selected.items())})
            count += 1
            if count > 1_000_000: raise GraphError('GRAPH_TOO_LARGE')
        nxt = page.get('@odata.nextLink')
        if nxt is None: break
        url = urlsplit(nxt) if isinstance(nxt, str) else None
        if not (url and url.scheme == 'https' and url.hostname == GRAPH): raise GraphError('GRAPH_RESPONSE')
        target = url.path + ('?' + url.query if url.query else '')
    return schema


LIST_TYPES = {'number': 'decimal', 'currency': 'decimal', 'boolean': 'boolean'}


def list_catalogue(settings, source):
    """A SharePoint list's visible columns with types from their definitions."""
    locator = settings_for(settings, 'sharepoint')
    access = token(settings)
    _, host, name = locator
    site = graph(access, f'/v1.0/sites/{host}:/sites/{quote(name)}')
    base = f"/v1.0/sites/{quote(str(site.get('id')), safe=',.')}/lists/{quote(list_name(source['path']))}"
    columns = graph(access, base + '/columns').get('value')
    if not isinstance(columns, list): raise GraphError('GRAPH_RESPONSE')
    out = []
    for c in columns:
        if not isinstance(c, dict) or not isinstance(c.get('name'), str) or c.get('hidden'): continue
        facet = next((k for k in LIST_TYPES if k in c), None)
        out.append({'name': c['name'], 'type': LIST_TYPES.get(facet, 'string'), 'nullable': not c.get('required', False),
                    'sourceType': next((k for k in ('text', 'number', 'currency', 'boolean', 'dateTime', 'choice',
                                                    'lookup', 'personOrGroup', 'calculated') if k in c), 'text')})
    return out


def scan(settings, kind, table, emit=None):
    """Return the JSON Schema of the table; when emit is given, emit every row."""
    locator = settings_for(settings, kind)
    access = token(settings)
    if table.get('entity') == 'list':
        require(kind == 'sharepoint', 'Lists are read from SharePoint sites')
        return scan_list(access, locator, table, emit)
    drive_id, path = drive(access, locator, table_path(table['path'], kind))
    items = files(access, drive_id, path, table['format'])
    if emit is None: items = items[:1]
    schema = None
    with tempfile.TemporaryDirectory(prefix='ingestron-graph-') as folder:
        for index, item in enumerate(items):
            local = Path(folder).resolve() / f'input-{index}'
            download(item, local)
            current, _ = scan_file({'path': str(local), 'format': table['format'], 'types': table['types']}, emit)
            local.unlink()
            if schema is not None and current != schema: raise GraphError('GRAPH_SCHEMA')
            schema = current
    return schema
