"""Salesforce objects through the REST API (PB-064 phase 7).

OAuth 2.0 client credentials against the org's My Domain, the object describe
resource for field types, and SOQL query with nextRecordsUrl paging. API
version pinned to v62.0. Documented at developer.salesforce.com (accessed
2026-10-01). Read only; no Bulk API jobs are created.
"""
import re
from decimal import Decimal
from urllib.parse import quote, urlencode, urlsplit

from rest_client import ApiError, call, errors

VERSION = 'v62.0'
MAX_ROWS = 1_000_000
HOST = re.compile(r'[a-z0-9-]+(\.[a-z0-9-]+)*\.(my\.salesforce\.com|force\.com)')
OBJECT = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,79}')
FIELD = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,79}')
ERRORS = errors('SF', 'Salesforce')
# Describe field types that read as numbers, integers and booleans; the rest are text.
NUMBER = {'double', 'currency', 'percent'}
INTEGER = {'int', 'long'}


def settings_for(settings):
    url = urlsplit(settings.get('instance_url') or '')
    if not (url.scheme == 'https' and url.hostname and HOST.fullmatch(url.hostname)
            and url.path in ('', '/') and not url.query):
        raise ValueError('instance_url must be https://<domain>.my.salesforce.com')
    for key in ('client_id', 'client_secret'):
        if not (isinstance(settings.get(key), str) and 0 < len(settings[key]) <= 1024):
            raise ValueError('Set client_id and client_secret (a secret reference)')
    return url.hostname


def token(settings, host):
    body = urlencode({'grant_type': 'client_credentials', 'client_id': settings['client_id'],
                      'client_secret': settings['client_secret']})
    value = call('SF', host, 'POST', '/services/oauth2/token',
                 {'Content-Type': 'application/x-www-form-urlencoded'}, body, {400: 'SF_AUTH'})
    access = value.get('access_token') if isinstance(value, dict) else None
    if not isinstance(access, str) or not access: raise ApiError('SF_RESPONSE')
    return access


def describe(host, access, obj):
    value = call('SF', host, 'GET', f'/services/data/{VERSION}/sobjects/{quote(obj)}/describe',
                 {'Authorization': 'Bearer ' + access})
    fields = value.get('fields') if isinstance(value, dict) else None
    if not isinstance(fields, list): raise ApiError('SF_RESPONSE')
    return {f['name']: f.get('type') for f in fields if isinstance(f, dict) and isinstance(f.get('name'), str)}


def kind(sf_type):
    return 'number' if sf_type in NUMBER else 'integer' if sf_type in INTEGER else \
        'boolean' if sf_type == 'boolean' else 'string'


def _value(value, expected):
    if value is None: return None
    if expected == 'boolean':
        if isinstance(value, bool): return value
    elif expected in ('integer', 'number'):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            number = Decimal(str(value))
            if expected == 'number': return number
            if number == number.to_integral_value(): return int(number)
    elif isinstance(value, str):
        return value
    raise ApiError('SF_SCHEMA')


def scan(settings, table, emit=None):
    host = settings_for(settings)
    obj, columns = table['object'], table['columns']
    access = token(settings, host)
    fields = describe(host, access, obj)
    if not set(columns) <= set(fields): raise ApiError('SF_SCHEMA')
    kinds = {c: kind(fields[c]) for c in columns}
    if any(kinds[c] != table['kinds'][c] for c in columns): raise ApiError('SF_SCHEMA')
    schema = {'type': 'object', 'additionalProperties': False,
              'properties': {c: {'type': ['null', kinds[c]]} for c in columns}}
    if emit is None: return schema
    soql = f"SELECT {', '.join(columns)} FROM {obj}"
    target, count = f'/services/data/{VERSION}/query?' + urlencode({'q': soql}), 0
    while target:
        page = call('SF', host, 'GET', target, {'Authorization': 'Bearer ' + access})
        records = page.get('records') if isinstance(page, dict) else None
        if not isinstance(records, list): raise ApiError('SF_RESPONSE')
        for record in records:
            if not isinstance(record, dict): raise ApiError('SF_RESPONSE')
            emit({c: _value(record.get(c), kinds[c]) for c in columns})
            count += 1
            if count > MAX_ROWS: raise ApiError('SF_TOO_LARGE')
        if page.get('done') is True: break
        nxt = page.get('nextRecordsUrl')
        if not (isinstance(nxt, str) and nxt.startswith(f'/services/data/{VERSION}/query/')):
            raise ApiError('SF_RESPONSE')
        target = nxt
    return schema
