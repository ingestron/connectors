"""Jira Cloud tables through the REST API v3 (PB-064 phase 7).

Basic authentication with an Atlassian account email and API token. Issues use
the enhanced search (POST /rest/api/3/search/jql) with a bounded JQL query and
nextPageToken paging; a repeated token or issue fails instead of looping.
Issue columns are `id`, `key` and field IDs from /rest/api/3/field; object
values become their name, value or display name, lists become JSON text.
Other tables have fixed fields. Table names follow the Lakeflow Connect Jira
tables. Documented at developer.atlassian.com (accessed 2026-10-01).
"""
import base64
import json
import re
from decimal import Decimal
from urllib.parse import urlencode, urlsplit

from rest_client import ApiError, call, errors

MAX_ROWS = 1_000_000
SITE = re.compile(r'[a-z0-9][a-z0-9-]{0,62}\.atlassian\.net')
DEFAULT_JQL = 'project IS NOT EMPTY ORDER BY created ASC'
ERRORS = errors('JIRA', 'Jira')
# Fixed tables: endpoint, paged by startAt, and their fields.
TABLES = {
    'projects': ('/rest/api/3/project/search', True,
                 {'id': 'string', 'key': 'string', 'name': 'string', 'projectTypeKey': 'string',
                  'simplified': 'boolean', 'style': 'string', 'isPrivate': 'boolean'}),
    'issue_types': ('/rest/api/3/issuetype', False,
                    {'id': 'string', 'name': 'string', 'description': 'string', 'subtask': 'boolean',
                     'hierarchyLevel': 'integer'}),
    'status': ('/rest/api/3/status', False,
               {'id': 'string', 'name': 'string', 'description': 'string', 'statusCategory': 'string'}),
    'users': ('/rest/api/3/users/search', True,
              {'accountId': 'string', 'accountType': 'string', 'displayName': 'string', 'active': 'boolean'}),
}
OBJECTS = ('issues', *TABLES)


def settings_for(settings):
    url = urlsplit(settings.get('site') or '')
    if not (url.scheme == 'https' and url.hostname and SITE.fullmatch(url.hostname)
            and url.path in ('', '/')):
        raise ValueError('site must be https://<name>.atlassian.net')
    if not (isinstance(settings.get('email'), str) and '@' in settings['email']):
        raise ValueError('Set email to the Atlassian account that owns the API token')
    if not (isinstance(settings.get('api_token'), str) and 0 < len(settings['api_token']) <= 1024):
        raise ValueError('Set api_token through its secret reference')
    auth = base64.b64encode(f"{settings['email']}:{settings['api_token']}".encode()).decode()
    return url.hostname, {'Authorization': 'Basic ' + auth, 'Accept': 'application/json'}


def kind(schema):
    t = (schema or {}).get('type')
    return 'number' if t == 'number' else 'string'


def issue_fields(host, headers):
    value = call('JIRA', host, 'GET', '/rest/api/3/field', headers)
    if not isinstance(value, list): raise ApiError('JIRA_RESPONSE')
    return {'id': 'string', 'key': 'string',
            **{f['id']: kind(f.get('schema')) for f in value if isinstance(f, dict) and isinstance(f.get('id'), str)}}


def flatten(value):
    if isinstance(value, dict):
        for key in ('name', 'value', 'displayName', 'key'):
            if isinstance(value.get(key), str): return value[key]
        return json.dumps(value, sort_keys=True, separators=(',', ':'))
    if isinstance(value, list): return json.dumps(value, sort_keys=True, separators=(',', ':'))
    return value


def _value(value, expected):
    value = flatten(value)
    if value is None: return None
    if expected == 'boolean' and isinstance(value, bool): return value
    if expected in ('integer', 'number') and isinstance(value, (int, float)) and not isinstance(value, bool):
        number = Decimal(str(value))
        if expected == 'number': return number
        if number == number.to_integral_value(): return int(number)
    if expected == 'string' and isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value)
    raise ApiError('JIRA_SCHEMA')


def _issues(host, headers, table, columns, emit):
    fields = [c for c in columns if c not in ('id', 'key')]
    token, count, tokens, ids = None, 0, set(), set()
    while True:
        body = {'jql': table.get('jql') or DEFAULT_JQL, 'fields': fields or ['id'], 'maxResults': 100,
                **({'nextPageToken': token} if token else {})}
        page = call('JIRA', host, 'POST', '/rest/api/3/search/jql',
                    {**headers, 'Content-Type': 'application/json'}, json.dumps(body))
        issues = page.get('issues') if isinstance(page, dict) else None
        if not isinstance(issues, list): raise ApiError('JIRA_RESPONSE')
        for issue in issues:
            if not isinstance(issue, dict) or issue.get('id') in ids: raise ApiError('JIRA_RESPONSE')
            ids.add(issue.get('id'))
            values = issue.get('fields') or {}
            emit({c: _value(issue.get(c) if c in ('id', 'key') else values.get(c), table['kinds'][c])
                  for c in columns})
            count += 1
            if count > MAX_ROWS: raise ApiError('JIRA_TOO_LARGE')
        token = page.get('nextPageToken')
        if page.get('isLast') is True or not token: return
        if token in tokens: raise ApiError('JIRA_RESPONSE')
        tokens.add(token)


def _fixed(host, headers, path, paged, table, columns, emit):
    start, count = 0, 0
    while True:
        target = path + ('?' + urlencode({'startAt': start, 'maxResults': 50}) if paged else '')
        page = call('JIRA', host, 'GET', target, headers)
        values = page.get('values') if isinstance(page, dict) else page
        if not isinstance(values, list): raise ApiError('JIRA_RESPONSE')
        for item in values:
            if not isinstance(item, dict): raise ApiError('JIRA_RESPONSE')
            emit({c: _value(item.get(c), table['kinds'][c]) for c in columns})
            count += 1
            if count > MAX_ROWS: raise ApiError('JIRA_TOO_LARGE')
        if not paged or not values or (isinstance(page, dict) and page.get('isLast') is True): return
        start += len(values)


def catalogue(settings, obj):
    """Issue fields from the fields API, or a table's fixed fields."""
    host, headers = settings_for(settings)
    fields = issue_fields(host, headers) if obj == 'issues' else TABLES[obj][2]
    key = 'accountId' if obj == 'users' else 'id'
    return [{'name': n, 'type': 'decimal' if k == 'number' else k, 'nullable': n != key,
             **({'key': True} if n == key else {})} for n, k in fields.items()]


def scan(settings, table, emit=None):
    host, headers = settings_for(settings)
    obj, columns = table['object'], table['columns']
    fields = issue_fields(host, headers) if obj == 'issues' else TABLES[obj][2]
    if not set(columns) <= set(fields): raise ApiError('JIRA_SCHEMA')
    kinds = table['kinds']
    for c in columns:
        if not (fields[c] == kinds[c] or (fields[c] == 'number' and kinds[c] == 'integer')
                or (obj == 'issues' and kinds[c] == 'string')):
            raise ApiError('JIRA_SCHEMA')
    schema = {'type': 'object', 'additionalProperties': False,
              'properties': {c: {'type': ['null', kinds[c]]} for c in columns}}
    if emit is None: return schema
    if obj == 'issues': _issues(host, headers, table, columns, emit)
    else: _fixed(host, headers, TABLES[obj][0], TABLES[obj][1], table, columns, emit)
    return schema
