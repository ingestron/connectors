"""Source-owned, read-only probes, metadata and explicitly requested samples.

Database catalogues use keyset pages. API/file sources expose only metadata
methods that can be performed without sampling. Secrets resolve in this process.
"""
import csv
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote, urlencode
from xml.etree import ElementTree


class AccessError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def secret(value):
    if isinstance(value, list): return [secret(v) for v in value]
    if not isinstance(value, dict): return value
    if '$secret' not in value: return {k: secret(v) for k, v in value.items()}
    ref = value['$secret']
    if set(value) != {'$secret'} or not isinstance(ref, dict) or set(ref) != {'env'}:
        raise AccessError('SECRET_REFERENCE')
    name = ref['env']
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name): raise AccessError('SECRET_REFERENCE')
    result = os.environ.get(name)
    if not result or len(result) > 1000000: raise AccessError('SECRET_MISSING')
    return result


def api(host, target, headers=None, method='GET'):
    connection = http.client.HTTPSConnection(host, timeout=30)
    try:
        connection.request(method, target, headers=headers or {})
        response = connection.getresponse()
        if response.status == 401: raise AccessError('ACCESS_AUTH')
        if response.status == 403: raise AccessError('ACCESS_FORBIDDEN')
        if response.status == 404: raise AccessError('ACCESS_NOT_FOUND')
        if response.status == 429: raise AccessError('ACCESS_RATE_LIMIT')
        if not 200 <= response.status < 300: raise AccessError('ACCESS_RESPONSE')
        body = response.read(1000001)
        if len(body) > 1000000: raise AccessError('ACCESS_TOO_LARGE')
        return body
    finally:
        connection.close()


def object_entry(source, name, kind='table', columns=None):
    identity = hashlib.sha256(json.dumps(source, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16]
    return {'id': 'table_' + identity, 'name': name, 'source': source, 'kind': kind,
            **({'columns': columns} if columns is not None else {})}


def database_connection(kind, settings, connect=None):
    if kind == 'sql-server':
        from sql_server_reader import connection_string
        if connect is None:
            from mssql_python import connect
        return connect(connection_string(settings['connection']), timeout=65)
    from dbapi_reader import DIALECTS, connection_settings
    config = connection_settings(kind, settings['connection'])
    return (connect or DIALECTS[kind]['connect'])(config)


def database(kind, action, settings, request, connect=None):
    if action == 'metadata':
        if kind == 'sql-server':
            from sql_server_reader import catalogue
            columns = lambda t: catalogue({"connection": settings["connection"], "object": t}, connect=connect)
        else:
            from dbapi_reader import catalogue, connection_settings
            config = connection_settings(kind, settings['connection'])
            columns = lambda t: catalogue(kind, config, t, connect=connect)
        return [object_entry(t, t['schema'] + '.' + t['table'], columns=columns(t)) for t in request['tables']], None
    db = database_connection(kind, settings, connect)
    try:
        cursor = db.cursor()
        if action == 'test':
            cursor.execute('SELECT 1 FROM dual' if kind == 'oracle' else 'SELECT 1')
            if cursor.fetchone()[0] != 1: raise AccessError('ACCESS_RESPONSE')
            return [], None
        limit = request.get('limit', 50)
        if type(limit) is not int or not 1 <= limit <= 200: raise AccessError('ACCESS_INPUT')
        schema, query = request.get('schema', ''), request.get('query', '')
        after = json.loads(request['cursor']) if request.get('cursor') else ['', '']
        if not isinstance(after, list) or len(after) != 2 or not all(isinstance(v, str) and len(v) <= 128 for v in after):
            raise AccessError('ACCESS_INPUT')
        # Search is literal, including SQL wildcard characters; no user SQL.
        search = '%' + query.replace('!', '!!').replace('%', '!%').replace('_', '!_').replace('[', '![') + '%'
        if kind == 'sql-server':
            sql = f"""SELECT TOP ({limit + 1}) s.name, t.name FROM sys.tables t
                JOIN sys.schemas s ON s.schema_id=t.schema_id WHERE t.is_ms_shipped=0
                AND (?='' OR s.name=?) AND t.name LIKE ? ESCAPE '!'
                AND (s.name>? OR (s.name=? AND t.name>?)) ORDER BY s.name,t.name"""
            parameters = (schema, schema, search, after[0], after[0], after[1])
        elif kind == 'oracle':
            sql = f"""SELECT owner, table_name FROM all_tables WHERE (:1 IS NULL OR owner=:2)
                AND table_name LIKE :3 ESCAPE '!'
                AND (owner>:4 OR (owner=:5 AND table_name>:6) OR :7 IS NULL)
                ORDER BY owner,table_name FETCH FIRST {limit + 1} ROWS ONLY"""
            parameters = (schema or None, schema or None, search, after[0] or None, after[0] or None, after[1] or None, after[0] or None)
        else:
            sql = f"""SELECT table_schema, table_name FROM information_schema.tables WHERE table_type='BASE TABLE'
                AND table_schema NOT IN ('information_schema','pg_catalog','mysql','performance_schema','sys')
                AND (%s='' OR table_schema=%s) AND table_name LIKE %s ESCAPE '!'
                AND (table_schema>%s OR (table_schema=%s AND table_name>%s))
                ORDER BY table_schema,table_name LIMIT {limit + 1}"""
            parameters = (schema, schema, search, after[0], after[0], after[1])
        cursor.execute(sql, parameters)
        rows = cursor.fetchmany(limit + 1)
        entries = [object_entry({'schema': s, 'table': t}, s + '.' + t) for s, t in rows[:limit]]
        return entries, json.dumps(list(rows[limit-1])) if len(rows) > limit else None
    finally:
        db.close()


def file_metadata(source):
    from files_reader import local_path, arrow_kind
    path = local_path(source)
    fmt = source['format']
    if fmt in ('csv', 'tsv'):
        with path.open(newline='', encoding='utf-8-sig') as handle:
            # Read the header only and bound it; no record sampling.
            header = handle.readline(65537)
        if len(header) > 65536: raise AccessError('ACCESS_TOO_LARGE')
        names = next(csv.reader([header], delimiter='\t' if fmt == 'tsv' else ','))
        if not names or len(names) > 500 or len(names) != len(set(names)): raise AccessError('ACCESS_INPUT')
        columns = [{'name': n, 'type': 'string', 'nullable': True} for n in names]
    elif fmt == 'parquet':
        import pyarrow.parquet as pq
        schema = pq.ParquetFile(path).schema_arrow
        if len(schema) > 500: raise AccessError('ACCESS_TOO_LARGE')
        columns = [{'name': f.name, 'type': arrow_kind(f.type), 'nullable': f.nullable} for f in schema]
    else:
        raise AccessError('SAMPLING_REQUIRED')
    return object_entry(source, path.name, 'file', columns)


def probe(kind, settings, source=None):
    if kind == 'files':
        if not source: raise AccessError('SOURCE_PATH_REQUIRED')
        from files_reader import local_path
        local_path(source)
        return 'file'
    if kind == 'azure-blob':
        from azure_blob_reader import endpoint, request_target
        if source:
            host, target = request_target(settings, source['path'])
        else:
            host, container, query = endpoint(settings)
            target = '/' + container + '?restype=container&' + query
        api(host, target, {'x-ms-version': '2023-11-03'}, 'HEAD')
        return 'metadata'
    if kind in ('s3', 'gcs'):
        from object_store_reader import request
        request(kind.upper(), settings, kind, 'HEAD', source['path'] if source else '')
        return 'metadata'
    if kind == 'sftp':
        from sftp_reader import OpenSsh
        OpenSsh(settings).run(['pwd'])
        return 'connection'
    if kind in ('sharepoint', 'onedrive'):
        from graph_reader import settings_for, token, graph
        locator = settings_for(settings, kind)
        access = token(settings)
        if locator[0] == 'user': graph(access, '/v1.0/users/' + quote(locator[1], safe='@') + '/drive')
        else: graph(access, '/v1.0/sites/' + locator[1] + ':/sites/' + quote(locator[2]))
        return 'metadata'
    if kind == 'salesforce':
        from salesforce_reader import settings_for, token, describe
        host = settings_for(settings)
        describe(host, token(settings, host), source.get('object', 'Account') if source else 'Account')
        return 'metadata'
    if kind == 'hubspot':
        from hubspot_reader import settings_for, properties
        properties(settings_for(settings), source.get('object', 'contacts') if source else 'contacts')
        return 'metadata'
    if kind == 'jira':
        from jira_reader import settings_for, issue_fields
        issue_fields(*settings_for(settings))
        return 'metadata'
    if kind == 'stripe':
        from stripe_reader import api_key
        api('api.stripe.com', '/v1/account', {'Authorization': 'Bearer ' + api_key(settings)})
        return 'authentication'
    if kind == 'github':
        repositories = settings.get('repositories', [])
        if not 1 <= len(repositories) <= 10: raise AccessError('ACCESS_INPUT')
        auth = settings.get('authentication', 'token' if settings.get('auth_token') else 'anonymous')
        if auth == 'token' and not settings.get('auth_token'): raise AccessError('SECRET_MISSING')
        headers = {'User-Agent': 'ingestron-source-access', 'Accept': 'application/vnd.github+json',
                   **({'Authorization': 'Bearer ' + settings['auth_token']} if auth == 'token' else {})}
        for repo in repositories:
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo): raise AccessError('ACCESS_INPUT')
            api('api.github.com', '/repos/' + repo, headers)
        return 'metadata'
    raise AccessError('ACCESS_UNSUPPORTED')


def crm(kind, action, settings, request):
    module = __import__(kind + '_reader')
    objects = ('Account', 'Contact', 'Opportunity', 'Lead', 'Case', 'Product2', 'Order', 'OrderItem', 'User') if kind == 'salesforce' else module.OBJECTS if hasattr(module, 'OBJECTS') else tuple(module.CATALOGUE)
    if action == 'inventory':
        # Declared object types, not a claim that each object is permitted.
        names = sorted(o for o in objects if request.get('query', '').casefold() in o.casefold())
        return [object_entry({'object': n}, n, 'object') for n in names], 'DECLARED_OBJECTS'
    entries = []
    for source in request['tables']:
        obj = source['object']
        if obj not in objects: raise AccessError('ACCESS_INPUT')
        if kind == 'stripe':
            # Pinned schema; unlike the old catalogue, never enumerate records.
            columns = [{'name': n, 'type': k, 'nullable': n != 'id', **({'key': True} if n == 'id' else {})}
                       for n, k in module.CATALOGUE[obj][1].items()]
        else:
            columns = module.catalogue(settings, obj)
        entries.append(object_entry(source, obj, 'object', columns))
    return entries, 'DECLARED_SCHEMA' if kind == 'stripe' else None


def github_metadata(action, settings, request):
    # The pinned reader declares its schema without fetching issue records.
    # Repository permissions belong to the separate access probe.
    if action == 'inventory':
        names = ['issues'] if request.get('query', '').casefold() in 'issues' else []
        return [object_entry({'stream': name}, name, 'object') for name in names], 'DECLARED_OBJECTS'
    from singer_runtime import source_config, read_catalog
    config = source_config({'connector': 'github@1.29.2', 'sourceSettings': settings})
    catalogue = read_catalog(Path(sys.executable).parent / 'tap-github', config, 30)
    issue = next((s for s in catalogue['streams'] if s.get('tap_stream_id') == 'issues'), None)
    if not issue: raise AccessError('ACCESS_UNSUPPORTED')
    columns = []
    for name, spec in sorted(issue['schema'].get('properties', {}).items()):
        types = spec.get('type', 'string')
        types = [t for t in (types if isinstance(types, list) else [types]) if t != 'null']
        kind = types[0] if len(types) == 1 else 'string'
        supported = kind in ('string', 'integer', 'number', 'boolean')
        columns.append({'name': name, 'type': kind if supported else 'string',
                        'nullable': True, **({'key': True} if name == 'id' else {}),
                        **({'supported': False, 'sourceType': kind} if not supported else {})})
    entries = []
    for source in request['tables']:
        if source != {'stream': 'issues'}: raise AccessError('ACCESS_INPUT')
        entries.append(object_entry(source, 'issues', 'object', columns))
    return entries, 'DECLARED_SCHEMA'


def execute(request, connect=None):
    kind, action = request['connector'], request['action']
    response = {'apiVersion': 'ingestron.source-access-result/v1', 'action': action,
                'status': 'succeeded', 'scope': 'metadata', 'tables': []}
    try:
        settings = secret(request['settings'])
        if action == 'sample':
            from source_sample import sample
            response['sample'] = sample(kind, settings, request, connect)
            response['scope'] = 'data'
        elif kind in ('sql-server', 'postgresql', 'mysql', 'oracle'):
            response['tables'], cursor = database(kind, action, settings, request, connect)
            if cursor: response['nextCursor'] = cursor
            response['scope'] = 'connection' if action == 'test' else 'metadata'
        elif action == 'test':
            response['scope'] = probe(kind, settings, request.get('source'))
        elif kind == 'files' and action == 'metadata':
            response['tables'] = [file_metadata(s) for s in request['tables']]
        elif kind in ('azure-blob', 's3', 'gcs', 'sftp', 'sharepoint', 'onedrive') and action == 'metadata':
            from source_sample import remote_file_read
            for source in request['tables']:
                if kind == 'sharepoint' and source.get('entity') == 'list':
                    from graph_reader import list_catalogue, list_name
                    entry = object_entry(source, list_name(source['path']), 'object', list_catalogue(settings, source))
                else:
                    # Schema is from a CSV/TSV header or Parquet footer, never inferred from sample rows.
                    if source.get('format') not in ('csv', 'tsv', 'parquet'): raise AccessError('SAMPLING_REQUIRED')
                    info = remote_file_read(kind, settings, source, file_metadata)
                    entry = object_entry(source, source['path'].rsplit('/', 1)[-1], 'file', info['columns'])
                response['tables'].append(entry)
        elif kind in ('salesforce', 'hubspot', 'jira', 'stripe'):
            response['tables'], code = crm(kind, action, settings, request)
            if code: response['code'] = code
        elif kind == 'github' and action in ('inventory', 'metadata'):
            response['tables'], code = github_metadata(action, settings, request)
            response['code'] = code
        else:
            raise AccessError('ACCESS_UNSUPPORTED')
        if len(response['tables']) > 200 or any(len(t.get('columns', [])) > 500 for t in response['tables']):
            raise AccessError('ACCESS_TOO_LARGE')
    except Exception as error:
        code = getattr(error, 'code', 'ACCESS_FAILED')
        if not isinstance(code, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{2,40}', code): code = 'ACCESS_FAILED'
        response.update(status='unsupported' if code in ('ACCESS_UNSUPPORTED', 'SAMPLING_REQUIRED', 'SOURCE_PATH_REQUIRED') else 'failed', code=code, tables=[])
        response.pop('nextCursor', None)
        response.pop('sample', None)
    return response


if __name__ == '__main__':
    try:
        path = Path(sys.argv[1])
        if path.stat().st_size > 1000000: raise AccessError('ACCESS_TOO_LARGE')
        result = execute(json.loads(path.read_text()))
    except Exception:
        result = {'apiVersion': 'ingestron.source-access-result/v1', 'action': 'test',
                  'status': 'failed', 'scope': 'connection', 'tables': [], 'code': 'ACCESS_INPUT'}
    print(json.dumps(result))
