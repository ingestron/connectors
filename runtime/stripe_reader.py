"""Read Stripe objects through the documented list API over HTTPS (PB-064 phase 4).

GET https://api.stripe.com/v1/<object>?limit=100&starting_after=<id> returns
{"object": "list", "data": [...], "has_more": bool}. Only top-level scalar fields
from the pinned catalogue below can be selected; types follow Stripe's published
API reference (accessed 2026-09-30). No write calls, no expansion, no redirects.
"""
import http.client
import json
import re
from urllib.parse import urlencode

HOST = 'api.stripe.com'
PAGE = 100
MAX_ROWS = 1_000_000
MAX_PAGE_BYTES = 16_000_000
KEY = re.compile(r'(rk|sk)_(test|live)_[A-Za-z0-9]{8,247}')

_COMMON = {'id': 'string', 'object': 'string', 'created': 'integer', 'livemode': 'boolean'}
# object list path -> (item "object" value, selectable scalar fields)
CATALOGUE = {
    'customers': ('customer', {**_COMMON, 'email': 'string', 'name': 'string', 'description': 'string',
                               'phone': 'string', 'currency': 'string', 'balance': 'integer',
                               'delinquent': 'boolean'}),
    'charges': ('charge', {**_COMMON, 'amount': 'integer', 'amount_captured': 'integer',
                           'amount_refunded': 'integer', 'currency': 'string', 'customer': 'string',
                           'description': 'string', 'paid': 'boolean', 'refunded': 'boolean',
                           'captured': 'boolean', 'status': 'string', 'payment_intent': 'string',
                           'receipt_email': 'string', 'failure_code': 'string',
                           'failure_message': 'string', 'balance_transaction': 'string'}),
    'payment_intents': ('payment_intent', {**_COMMON, 'amount': 'integer', 'amount_received': 'integer',
                                           'currency': 'string', 'customer': 'string',
                                           'description': 'string', 'status': 'string',
                                           'capture_method': 'string', 'canceled_at': 'integer',
                                           'cancellation_reason': 'string', 'latest_charge': 'string'}),
    'invoices': ('invoice', {**_COMMON, 'customer': 'string', 'status': 'string', 'currency': 'string',
                             'amount_due': 'integer', 'amount_paid': 'integer',
                             'amount_remaining': 'integer', 'total': 'integer', 'subtotal': 'integer',
                             'number': 'string', 'due_date': 'integer', 'collection_method': 'string',
                             'customer_email': 'string', 'period_start': 'integer',
                             'period_end': 'integer'}),
    'products': ('product', {**_COMMON, 'name': 'string', 'description': 'string', 'active': 'boolean',
                             'updated': 'integer', 'url': 'string', 'default_price': 'string'}),
    'prices': ('price', {**_COMMON, 'active': 'boolean', 'currency': 'string', 'unit_amount': 'integer',
                         'product': 'string', 'type': 'string', 'nickname': 'string',
                         'billing_scheme': 'string', 'lookup_key': 'string'}),
    'subscriptions': ('subscription', {**_COMMON, 'customer': 'string', 'status': 'string',
                                       'currency': 'string', 'cancel_at_period_end': 'boolean',
                                       'canceled_at': 'integer', 'start_date': 'integer',
                                       'ended_at': 'integer', 'collection_method': 'string',
                                       'description': 'string'}),
    'refunds': ('refund', {**_COMMON, 'amount': 'integer', 'charge': 'string', 'currency': 'string',
                           'payment_intent': 'string', 'reason': 'string', 'status': 'string'}),
    'balance_transactions': ('balance_transaction', {**_COMMON, 'amount': 'integer',
                                                     'available_on': 'integer', 'currency': 'string',
                                                     'description': 'string', 'fee': 'integer',
                                                     'net': 'integer', 'status': 'string',
                                                     'type': 'string', 'reporting_category': 'string',
                                                     'source': 'string'}),
}

ERRORS = {
    'STRIPE_AUTH': 'Stripe rejected the API key; check or replace it.',
    'STRIPE_FORBIDDEN': 'The Stripe key cannot read this object; grant read access to it on the restricted key.',
    'STRIPE_RATE_LIMIT': 'Stripe rate limit reached; wait before retrying.',
    'STRIPE_UNAVAILABLE': 'Stripe is unavailable; retry later.',
    'STRIPE_RESPONSE': 'Stripe returned an unexpected response; check the object name and API version.',
    'STRIPE_SCHEMA': 'Stripe object fields differ from the reviewed contract; rediscover and review.',
    'STRIPE_TOO_LARGE': 'The Stripe object has more than one million records; narrow the read.',
    'STRIPE_NETWORK': 'Cannot reach api.stripe.com; check network access and retry.',
}


class StripeError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def api_key(settings):
    key = settings.get('api_key')
    if not (isinstance(key, str) and KEY.fullmatch(key)):
        raise ValueError('Set a Stripe secret or restricted key (sk_ or rk_) through its secret reference')
    return key


def fields(obj):
    if obj not in CATALOGUE:
        raise ValueError('Stripe object must be one of ' + ', '.join(sorted(CATALOGUE)))
    return CATALOGUE[obj][1]


def _status(status):
    if status == 200: return
    if status == 401: raise StripeError('STRIPE_AUTH')
    if status == 403: raise StripeError('STRIPE_FORBIDDEN')
    if status == 429: raise StripeError('STRIPE_RATE_LIMIT')
    if status >= 500: raise StripeError('STRIPE_UNAVAILABLE')
    raise StripeError('STRIPE_RESPONSE')


def pages(key, obj):
    """Yield each page's items; never follows redirects or echoes response bodies."""
    after = None
    while True:
        query = {'limit': PAGE, **({'starting_after': after} if after else {})}
        connection = None
        try:
            connection = http.client.HTTPSConnection(HOST, timeout=30)
            connection.request('GET', f'/v1/{obj}?{urlencode(query)}',
                               headers={'Authorization': 'Bearer ' + key,
                                        'User-Agent': 'ingestron-stripe-connector'})
            response = connection.getresponse()
            _status(response.status)
            body = response.read(MAX_PAGE_BYTES + 1)
        except StripeError:
            raise
        except Exception:
            # Never include the key, URL or transport exception text.
            raise StripeError('STRIPE_NETWORK') from None
        finally:
            if connection is not None: connection.close()
        if len(body) > MAX_PAGE_BYTES: raise StripeError('STRIPE_RESPONSE')
        try:
            page = json.loads(body)
        except ValueError:
            raise StripeError('STRIPE_RESPONSE') from None
        if not (isinstance(page, dict) and page.get('object') == 'list'
                and isinstance(page.get('data'), list) and isinstance(page.get('has_more'), bool)):
            raise StripeError('STRIPE_RESPONSE')
        yield page['data']
        if not page['has_more'] or not page['data']: return
        after = page['data'][-1].get('id')
        if not isinstance(after, str): raise StripeError('STRIPE_RESPONSE')


def _matches(value, kind):
    if value is None: return True
    if kind == 'integer': return isinstance(value, int) and not isinstance(value, bool)
    if kind == 'boolean': return isinstance(value, bool)
    return isinstance(value, str)


def catalogue(settings, obj):
    """The object's selectable fields; one page is read to check access."""
    catalogue_fields = fields(obj)
    scan(settings, {'object': obj, 'columns': ['id']})
    return [{'name': name, 'type': kind, 'nullable': name != 'id', **({'key': True} if name == 'id' else {})}
            for name, kind in catalogue_fields.items()]


def scan(settings, table, emit=None):
    """Return the JSON Schema of the selected fields; when emit is given, read every record."""
    key, obj, columns = api_key(settings), table['object'], table['columns']
    catalogue = fields(obj)
    schema = {'type': 'object', 'additionalProperties': False,
              'properties': {c: {'type': ['null', catalogue[c]]} for c in columns}}
    expected = CATALOGUE[obj][0]
    count = 0
    # Discovery reads one page so access and field shapes are checked before review.
    for items in pages(key, obj):
        for item in items:
            if not (isinstance(item, dict) and item.get('object') == expected
                    and all(c in item and _matches(item[c], catalogue[c]) for c in columns)):
                raise StripeError('STRIPE_SCHEMA')
            count += 1
            if count > MAX_ROWS: raise StripeError('STRIPE_TOO_LARGE')
            if emit: emit({c: item[c] for c in columns})
        if emit is None: break
    return schema
