"""Bounded HTTPS JSON calls for API connectors (PB-064 phase 7).

No redirects are followed, response bodies are capped, and failures become a
connector error code: response text, URLs and credentials are never echoed.
"""
import http.client
import json

MAX_RESPONSE = 16_000_000


class ApiError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def status_code(prefix, status):
    if 200 <= status < 300: return None
    if status == 401: return prefix + '_AUTH'
    if status == 403: return prefix + '_FORBIDDEN'
    if status == 404: return prefix + '_NOT_FOUND'
    if status == 429: return prefix + '_RATE_LIMIT'
    if status >= 500: return prefix + '_UNAVAILABLE'
    return prefix + '_RESPONSE'


def call(prefix, host, method, target, headers, body=None, status_map=None):
    """Return the decoded JSON body of one request, or raise ApiError."""
    connection = None
    try:
        connection = http.client.HTTPSConnection(host, timeout=60)
        connection.request(method, target, body=body, headers=headers)
        response = connection.getresponse()
        status = response.status
        data = response.read(MAX_RESPONSE + 1)
    except ApiError:
        raise
    except Exception:
        raise ApiError(prefix + '_NETWORK') from None
    finally:
        if connection is not None: connection.close()
    code = (status_map or {}).get(status) or status_code(prefix, status)
    if code: raise ApiError(code)
    if len(data) > MAX_RESPONSE: raise ApiError(prefix + '_TOO_LARGE')
    try:
        return json.loads(data)
    except ValueError:
        raise ApiError(prefix + '_RESPONSE') from None


def errors(prefix, label, extra=None):
    """Standard messages for one connector's codes."""
    return {
        prefix + '_AUTH': f'{label} rejected the credentials; check or replace them.',
        prefix + '_FORBIDDEN': f'{label} denied access; grant read access to the selected objects.',
        prefix + '_NOT_FOUND': f'{label} could not find the object; check its name and access.',
        prefix + '_RATE_LIMIT': f'{label} rate limit reached; wait before retrying.',
        prefix + '_UNAVAILABLE': f'{label} is unavailable; retry later.',
        prefix + '_RESPONSE': f'{label} returned an unexpected response.',
        prefix + '_SCHEMA': f'{label} fields differ from the reviewed contract; rediscover and review.',
        prefix + '_TOO_LARGE': f'The {label} object has more than one million records or an oversized response.',
        prefix + '_NETWORK': f'Cannot reach {label}; check network access and retry.',
        **(extra or {}),
    }


def kind_of(contract_type):
    """Map a contracted column type to a value kind."""
    kind = contract_type.upper()
    if kind == 'STRING': return 'string'
    if kind in ('BIGINT', 'INT', 'INTEGER', 'SMALLINT'): return 'integer'
    if kind.startswith('DECIMAL(') or kind in ('DOUBLE', 'FLOAT'): return 'number'
    if kind == 'BOOLEAN': return 'boolean'
    raise ValueError('API connectors support STRING, integer, DECIMAL, DOUBLE and BOOLEAN contract types')
