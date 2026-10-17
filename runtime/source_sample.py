"""Explicit bounded data previews. No output/state writes and no arbitrary SQL."""
from datetime import date, datetime, time
from decimal import Decimal
import json
import math

MAX_ROWS = 50
MAX_COLUMNS = 100
MAX_CELL = 500

class SampleError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

class SampleComplete(Exception):
    pass

def cell(value):
    if value is None or isinstance(value, bool): return value
    if isinstance(value, int): return value if abs(value) <= 9007199254740991 else str(value)[:MAX_CELL]
    if isinstance(value, float):
        if not math.isfinite(value): raise SampleError('SAMPLE_VALUE')
        return value
    if isinstance(value, (date, datetime, time)): return value.isoformat()[:MAX_CELL]
    if isinstance(value, (str, Decimal)): return str(value)[:MAX_CELL].encode('utf-16-le')[:MAX_CELL * 2].decode('utf-16-le', errors='ignore')
    raise SampleError('SAMPLE_VALUE')

def selected(columns, request):
    available = {c['name']: c for c in columns if c.get('supported', True)}
    names = request.get('columns') or list(available)[:MAX_COLUMNS]
    if not isinstance(names, list) or not 1 <= len(names) <= MAX_COLUMNS or len(set(names)) != len(names) or not all(isinstance(n, str) and n in available for n in names):
        raise SampleError('SAMPLE_COLUMNS')
    return [available[n] for n in names]

def database_sample(kind, settings, request, connect=None):
    from source_access import database_connection
    source = request['source']
    if kind == 'sql-server':
        from sql_server_reader import catalogue, quote
        columns = catalogue({'connection': settings['connection'], 'object': source}, connect=connect)
        limit_sql = lambda sql, n: sql.replace('SELECT ', f'SELECT TOP ({n}) ', 1)
    else:
        from dbapi_reader import catalogue, connection_settings, DIALECTS
        columns = catalogue(kind, connection_settings(kind, settings['connection']), source, connect=connect)
        quote, limit_sql = DIALECTS[kind]['quote'], DIALECTS[kind]['limit']
    fields = selected(columns, request)
    # Names are validated/quoted by the source reader; row limit is a validated integer.
    sql = limit_sql(f"SELECT {', '.join(quote(c['name']) for c in fields)} FROM {quote(source['schema'])}.{quote(source['table'])}", request['limit'] + 1)
    db = database_connection(kind, settings, connect)
    try:
        cursor = db.cursor()
        cursor.execute(sql)
        rows = cursor.fetchmany(request['limit'] + 1)
        if any(len(row) != len(fields) for row in rows): raise SampleError('SAMPLE_SHAPE')
        return {'columns': [c['name'] for c in fields], 'rows': [[cell(v) for v in row] for row in rows[:request['limit']]], 'truncated': len(rows) > request['limit']}
    finally:
        db.close()

def file_sample(request):
    from files_reader import local_path, raw_rows
    source = request['source']
    path = local_path(source)
    # JSON requires an entire array parse; bound that read separately.
    if source['format'] == 'json' and path.stat().st_size > 1_000_000: raise SampleError('SAMPLE_TOO_LARGE')
    with path.open('rb') as handle:
        records = raw_rows(handle, source['format'])
        names, _ = next(records)
        rows, more = [], False
        for record in records:
            if len(rows) == request['limit']:
                more = True
                break
            if not isinstance(record, dict): raise SampleError('SAMPLE_SHAPE')
            if not names: names = list(record)
            if set(record) != set(names): raise SampleError('SAMPLE_SHAPE')
            chosen = request.get('columns') or names[:MAX_COLUMNS]
            if not chosen or len(set(chosen)) != len(chosen) or not set(chosen) <= set(names): raise SampleError('SAMPLE_COLUMNS')
            rows.append([cell(record.get(n)) for n in chosen])
        chosen = request.get('columns') or names[:MAX_COLUMNS]
        if not chosen or len(set(chosen)) != len(chosen) or not set(chosen) <= set(names): raise SampleError('SAMPLE_COLUMNS')
        return {'columns': chosen, 'rows': rows, 'truncated': more}

def api_sample(kind, settings, request):
    import importlib
    module = importlib.import_module(kind + '_reader')
    source = request['source']
    columns = module.catalogue(settings, source['object'])
    fields = selected(columns, request)
    table = {**source, 'columns': [c['name'] for c in fields], 'kinds': {c['name']: 'number' if c['type'] == 'decimal' else c['type'] for c in fields}}
    rows, more = [], False
    def emit(record):
        nonlocal more
        if len(rows) == request['limit']:
            more = True
            raise SampleComplete()
        if not isinstance(record, dict): raise SampleError('SAMPLE_SHAPE')
        rows.append([cell(record.get(c['name'])) for c in fields])
    try:
        module.scan(settings, table, emit, sample_limit=request['limit'])
    except SampleComplete:
        pass
    return {'columns': table['columns'], 'rows': rows, 'truncated': more}

def remote_file_read(kind, settings, source, inspect):
    """Read one explicit remote file, never expand a folder into a sample."""
    import tempfile
    from pathlib import Path
    from urllib.parse import quote, unquote
    from files_reader import MAX_BYTES
    if source.get('format') not in ('csv', 'tsv', 'json', 'jsonl', 'parquet'):
        raise SampleError('SAMPLE_FORMAT')
    with tempfile.TemporaryDirectory(prefix='ingestron-sample-') as folder:
        local = Path(folder).resolve() / 'input'
        if kind == 'azure-blob':
            from azure_blob_reader import download
            download(settings, source['path'], local)
        elif kind in ('s3', 'gcs'):
            from object_store_reader import request as read, table_path
            data, _ = read(kind.upper(), settings, kind, 'GET', table_path(source['path']), limit=MAX_BYTES)
            local.write_bytes(data)
        elif kind == 'sftp':
            from sftp_reader import OpenSsh, table_path
            path = table_path(source['path'])
            remote = OpenSsh(settings)
            entries = remote.list(path)
            if len(entries) != 1 or entries[0][2] or entries[0][0] != path.rsplit('/', 1)[-1]:
                raise SampleError('SAMPLE_FILE_REQUIRED')
            size = entries[0][1]
            if not 0 <= size <= MAX_BYTES: raise SampleError('SAMPLE_TOO_LARGE')
            remote.get(path, str(local))
            if not local.is_file() or local.stat().st_size != size: raise SampleError('SAMPLE_CHANGED')
        else:
            from graph_reader import settings_for, token, drive, graph, table_path, download
            locator = settings_for(settings, kind)
            access = token(settings)
            drive_id, path = drive(access, locator, table_path(source['path'], kind))
            item = graph(access, f"/v1.0/drives/{quote(drive_id)}/root:/{quote(unquote(path))}")
            if 'file' not in item: raise SampleError('SAMPLE_FILE_REQUIRED')
            download(item, local)
        return inspect({'path': str(local), 'format': source['format']})

def remote_file_sample(kind, settings, request):
    return remote_file_read(kind, settings, request['source'], lambda source: file_sample({**request, 'source': source}))

def sharepoint_list_sample(settings, request):
    from graph_reader import list_catalogue, settings_for, token, scan_list
    source = request['source']
    fields = selected(list_catalogue(settings, source), request)
    table = {**source, 'types': {c['name']: c['type'] for c in fields}}
    rows, more = [], False
    def emit(record):
        nonlocal more
        if len(rows) == request['limit']:
            more = True
            raise SampleComplete()
        rows.append([cell(record.get(c['name'])) for c in fields])
    try:
        scan_list(token(settings), settings_for(settings, 'sharepoint'), table, emit, sample_limit=request['limit'])
    except SampleComplete:
        pass
    return {'columns': [c['name'] for c in fields], 'rows': rows, 'truncated': more}

def github_sample(settings, request):
    """Issues/PRs use the pinned tap's scalar schema and repository context."""
    from source_access import github_metadata, api
    from singer_runtime import source_config
    from urllib.parse import urlencode
    config = source_config({'connector': 'github@1.29.2', 'sourceSettings': dict(settings)})
    if len(config['repositories']) > 10: raise SampleError('SAMPLE_REPOSITORIES')
    entries, _ = github_metadata('metadata', settings, {'tables': [request['source']]})
    fields = selected(entries[0]['columns'], request)
    headers = {'User-Agent': 'ingestron-source-access', 'Accept': 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2022-11-28',
               **({'Authorization': 'Bearer ' + config['auth_token']} if config.get('auth_token') else {})}
    rows, more = [], False
    for repository in config['repositories']:
        org, repo = repository.split('/')
        detail = json.loads(api('api.github.com', '/repos/' + repository, headers))
        if not isinstance(detail, dict) or type(detail.get('id')) is not int: raise SampleError('SAMPLE_SHAPE')
        page = 1
        while True:
            count = request['limit'] + 1 - len(rows)
            records = json.loads(api('api.github.com', '/repos/' + repository + '/issues?' + urlencode({'state':'all','per_page':count,'page':page}), headers))
            if not isinstance(records, list) or len(records) > count: raise SampleError('SAMPLE_SHAPE')
            for record in records:
                if len(rows) == request['limit']:
                    more = True
                    break
                if not isinstance(record, dict): raise SampleError('SAMPLE_SHAPE')
                record = {**record, 'org': org, 'repo': repo, 'repo_id': detail['id'],
                          'type': 'pull_request' if 'pull_request' in record else 'issue'}
                for name in ('title', 'body'):
                    if isinstance(record.get(name), str): record[name] = record[name].replace('\x00', '')
                rows.append([cell(record.get(c['name'])) for c in fields])
            if more or len(records) < count: break
            # All preceding pages are full, so this page number stays stable.
            page += 1
        if more: break
    return {'columns': [c['name'] for c in fields], 'rows': rows, 'truncated': more}

def sample(kind, settings, request, connect=None):
    limit = request.get('limit', 20)
    if type(limit) is not int or not 1 <= limit <= MAX_ROWS: raise SampleError('SAMPLE_LIMIT')
    names = request.get('columns')
    if names is not None and (not isinstance(names, list) or not 1 <= len(names) <= MAX_COLUMNS or not all(isinstance(n, str) for n in names)):
        raise SampleError('SAMPLE_COLUMNS')
    request = {**request, 'limit': limit}
    if kind in ('sql-server', 'postgresql', 'mysql', 'oracle'): result = database_sample(kind, settings, request, connect)
    elif kind == 'files': result = file_sample(request)
    elif kind in ('salesforce', 'hubspot', 'jira', 'stripe'): result = api_sample(kind, settings, request)
    elif kind == 'sharepoint' and request['source'].get('entity') == 'list': result = sharepoint_list_sample(settings, request)
    elif kind in ('azure-blob', 's3', 'gcs', 'sftp', 'sharepoint', 'onedrive'): result = remote_file_sample(kind, settings, request)
    elif kind == 'github': result = github_sample(settings, request)
    else: raise SampleError('ACCESS_UNSUPPORTED')
    while len(json.dumps(result).encode()) > 500_000 and result['rows']:
        result['rows'].pop()
        result['truncated'] = True
    return result
