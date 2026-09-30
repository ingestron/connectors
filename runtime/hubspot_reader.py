"""HubSpot CRM objects through the CRM v3 API (PB-064 phase 7).

A private app access token, the properties API for field types, and the
objects API with cursor (`after`) paging. Object names follow the Lakeflow
Connect HubSpot tables so a table reads alike on every route. Documented at
developers.hubspot.com (accessed 2026-10-01). Read only.
"""
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlencode

from rest_client import ApiError, call, errors

HOST = 'api.hubapi.com'
MAX_ROWS = 1_000_000
OBJECTS = ('calls', 'companies', 'contacts', 'deals', 'emails', 'leads', 'line_items', 'meetings',
           'notes', 'orders', 'products', 'tasks', 'tickets')
# Record-level fields beside the object's properties.
RECORD = {'id': 'string', 'createdAt': 'string', 'updatedAt': 'string', 'archived': 'boolean'}
ERRORS = errors('HUBSPOT', 'HubSpot')


def settings_for(settings):
    token = settings.get('access_token')
    if not (isinstance(token, str) and 8 <= len(token) <= 1024):
        raise ValueError('Set access_token (a private app token) through its secret reference')
    return token


def kind(hubspot_type):
    return {'number': 'number', 'bool': 'boolean'}.get(hubspot_type, 'string')


def properties(token, obj):
    value = call('HUBSPOT', HOST, 'GET', f'/crm/v3/properties/{quote(obj)}',
                 {'Authorization': 'Bearer ' + token})
    results = value.get('results') if isinstance(value, dict) else None
    if not isinstance(results, list): raise ApiError('HUBSPOT_RESPONSE')
    return {p['name']: kind(p.get('type')) for p in results if isinstance(p, dict) and isinstance(p.get('name'), str)}


def _value(value, expected):
    """HubSpot returns property values as text; convert to the contract type."""
    if value is None or value == '': return None
    if expected == 'boolean':
        if isinstance(value, bool): return value
        if value in ('true', 'false'): return value == 'true'
    elif expected in ('number', 'integer'):
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            raise ApiError('HUBSPOT_SCHEMA') from None
        if expected == 'number': return number
        if number == number.to_integral_value(): return int(number)
    elif isinstance(value, str):
        return value
    raise ApiError('HUBSPOT_SCHEMA')


def scan(settings, table, emit=None):
    token, obj, columns = settings_for(settings), table['object'], table['columns']
    fields = {**properties(token, obj), **RECORD}
    if not set(columns) <= set(fields): raise ApiError('HUBSPOT_SCHEMA')
    kinds = table['kinds']
    for c in columns:
        # Numbers may be contracted as integers; everything else must match.
        if not (fields[c] == kinds[c] or (fields[c] == 'number' and kinds[c] == 'integer')):
            raise ApiError('HUBSPOT_SCHEMA')
    schema = {'type': 'object', 'additionalProperties': False,
              'properties': {c: {'type': ['null', kinds[c]]} for c in columns}}
    if emit is None: return schema
    props = sorted(c for c in columns if c not in RECORD)
    after, count, seen = None, 0, set()
    while True:
        query = {'limit': 100, 'archived': 'false', **({'properties': ','.join(props)} if props else {}),
                 **({'after': after} if after else {})}
        page = call('HUBSPOT', HOST, 'GET', f'/crm/v3/objects/{quote(obj)}?{urlencode(query)}',
                    {'Authorization': 'Bearer ' + token})
        results = page.get('results') if isinstance(page, dict) else None
        if not isinstance(results, list): raise ApiError('HUBSPOT_RESPONSE')
        for record in results:
            values = record.get('properties') if isinstance(record, dict) else None
            if not isinstance(values, dict): raise ApiError('HUBSPOT_RESPONSE')
            emit({c: _value(record.get(c) if c in RECORD else values.get(c), kinds[c]) for c in columns})
            count += 1
            if count > MAX_ROWS: raise ApiError('HUBSPOT_TOO_LARGE')
        after = ((page.get('paging') or {}).get('next') or {}).get('after')
        if after is None: break
        if not isinstance(after, str) or after in seen: raise ApiError('HUBSPOT_RESPONSE')
        seen.add(after)
    return schema
