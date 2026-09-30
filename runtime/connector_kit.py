"""The Ingestron connector interface (PB-064 phase 3).

A connector says how to reach a source and read its tables. The shared runtime
owns everything else: locked project checks, secret resolution, review and
approval, projection to the reviewed contract, type conversion, spooling,
schema-drift checks, quality rules, atomic commit and receipts. Connectors never
write outputs or state.

Table connectors implement:

    settings(settings) -> dict    validate the connection settings (secrets resolved)
    table(source, columns) -> dict  validate one table's source; return what scan needs
    scan(settings, table, emit=None) -> dict
        return the table's JSON Schema; when emit is given, also call emit(row)
        for every row. Raise SourceError(code) for failures users can act on;
        codes and messages are declared in `errors` and never carry source data.

The connection holds the endpoint, scope and credentials; each table's source
names one object in the source's own terms ({schema, table} for databases,
{path, format} for files and object stores, {stream} for APIs).
"""
import tempfile

import snapshot_runtime as workflow
from singer_bridge import canonical, digest

SourceError = workflow.SourceError
MAX_RECORD = 2_000_000


def _spool_line(spool, stream, row):
    line = (canonical({'type': 'RECORD', 'stream': stream, 'record': row}) + '\n').encode()
    workflow.check(len(line) <= MAX_RECORD, 'Record exceeds 2 MB')
    spool.write(line)


def _selected(catalog):
    return {s['tap_stream_id']: s for s in catalog['streams']
            if any(m.get('breadcrumb') == [] and m.get('metadata', {}).get('selected')
                   for m in s.get('metadata', []))}


class TableConnector:
    """Base for connectors that read several contracted tables per connection."""
    name = 'source'
    table_keys = frozenset()
    optional_keys = frozenset()
    errors = {}

    def settings(self, settings):
        workflow.check(settings == {}, f'{self.name} connection settings must be empty')
        return settings

    def table(self, source, columns):
        return {**source, 'columns': [column['name'] for column in columns]}

    def scan(self, settings, table, emit=None):
        raise NotImplementedError

    def catalogue(self, settings, source):
        """Every field one table source offers, before a contract exists:
        [{'name', 'type', 'nullable', 'key'?, 'sourceType'?, 'supported'?}]."""
        workflow.check(False, f'{self.name} cannot list fields before a contract yet')


SAMPLE = 1000
_INTEGER = __import__('re').compile(r'-?(0|[1-9][0-9]*)')
_DECIMAL = __import__('re').compile(r'-?(0|[1-9][0-9]*)\.[0-9]+')


def columns_from_schema(schema, sample=(), keys=()):
    """Catalogue columns from a discovered JSON Schema. Text columns are
    suggested as integer, decimal or boolean when every sampled value fits."""
    columns = []
    for name, spec in schema.get('properties', {}).items():
        types = spec.get('type', 'string')
        types = types if isinstance(types, list) else [types]
        kind = next((t for t in types if t != 'null'), 'string')
        values = [row.get(name) for row in sample if row.get(name) not in (None, '')]
        if kind == 'string' and values and all(isinstance(v, str) for v in values):
            if all(_INTEGER.fullmatch(v) for v in values): kind = 'integer'
            elif all(_INTEGER.fullmatch(v) or _DECIMAL.fullmatch(v) for v in values): kind = 'decimal'
            elif all(v in ('true', 'false') for v in values): kind = 'boolean'
        columns.append({'name': name, 'type': kind, 'nullable': 'null' in types or name not in schema.get('required', []),
                        **({'key': True} if name in keys else {})})
    return columns


def sampled(scan):
    """Run scan(emit) keeping the first SAMPLE rows for type suggestions."""
    rows = []
    schema = scan(lambda row: rows.append(row) if len(rows) < SAMPLE else None)
    return schema, rows


def install(connector):
    """Wire a table connector into the shared reviewed snapshot workflow."""
    workflow.ERRORS.update(connector.errors)

    def source_config(config):
        workflow.check('projectLock' in config and 'sourceSettings' in config,
                       f'{connector.name} table bindings require a locked project')
        settings = connector.settings(workflow.resolve_secrets(config['sourceSettings']))
        tables = config['projectLock']['tables']
        workflow.check(isinstance(tables, dict) and 1 <= len(tables) <= 100,
                       f'Select 1–100 {connector.name} tables')
        objects = {}
        for stream, table in tables.items():
            workflow.safe_name(stream)
            source = dict(table['source'])
            keys = set(source) - {'stream'}
            workflow.check('stream' in source and source.pop('stream') == stream
                           and set(connector.table_keys) <= keys
                           <= set(connector.table_keys) | set(connector.optional_keys),
                           f'{connector.name} table source differs from its stream identity')
            columns = table['columns']
            names = [column['name'] for column in columns]
            workflow.check(isinstance(columns, list) and 1 <= len(columns) <= 500
                           and len(names) == len(set(names)),
                           'ODCS contract must select 1–500 distinct columns')
            objects[stream] = connector.table(source, columns)
        return {'settings': settings, 'objects': objects}

    def output(executable, source, catalog, timeout, discover=False, protocol='singer'):
        workflow.check(set(source) == {'settings', 'objects'}, f'Invalid locked {connector.name} source')
        if discover:
            streams = [{'tap_stream_id': stream, 'stream': stream,
                        'schema': connector.scan(source['settings'], table), 'metadata': []}
                       for stream, table in source['objects'].items()]
            yield canonical({'streams': streams}).encode()
            return
        selected = _selected(catalog)
        workflow.check(set(selected) == set(source['objects']),
                       f'Reviewed {connector.name} table selection changed')
        # Spool every table before yielding any record: a failure in the last
        # table cannot publish records from earlier ones.
        with tempfile.TemporaryFile(mode='w+b') as spool:
            schemas = []
            for stream, table in source['objects'].items():
                schema = connector.scan(source['settings'], table,
                                        lambda row, stream=stream: _spool_line(spool, stream, row))
                workflow.check(digest(schema) == digest(selected[stream]['schema']),
                               'Source schema changed; rediscover and review')
                schemas.append((stream, schema))
            for stream, schema in schemas:
                yield (canonical({'type': 'SCHEMA', 'stream': stream, 'schema': schema}) + '\n').encode()
            spool.seek(0)
            yield from spool

    base_review = workflow.review

    def catalogue(config, folder):
        """Fields per table from the source itself; no contract needed (PB-064 phase 6)."""
        identity = workflow.runtime_identity(config, folder)
        workflow.check('projectLock' in config and 'sourceSettings' in config,
                       f'{connector.name} discovery requires a locked project')
        settings = connector.settings(workflow.resolve_secrets(config['sourceSettings']))
        tables = config['projectLock']['tables']
        workflow.check(isinstance(tables, dict) and 1 <= len(tables) <= 100,
                       f'Select 1–100 {connector.name} tables')
        result = {}
        for stream, table in tables.items():
            workflow.safe_name(stream)
            source = dict(table['source'])
            keys = set(source) - {'stream'}
            workflow.check(source.pop('stream', None) == stream
                           and set(connector.table_keys) <= keys
                           <= set(connector.table_keys) | set(connector.optional_keys),
                           f'{connector.name} table source differs from its stream identity')
            result[stream] = {'columns': connector.catalogue(settings, source)}
        return {'apiVersion': 'ingestron.source-catalogue/v1', 'identity': identity, 'tables': result}

    def review(discovery, selection, authored_contracts=None):
        streams = [s['tap_stream_id'] for s in discovery['catalog']['streams']]
        workflow.check(set(selection) == set(streams) and len(streams) == len(set(streams)),
                       f'Review every table selected by the locked {connector.name} flow')
        workflow.CATALOGUE[0]['supportedStreams'] = streams
        return base_review(discovery, selection, authored_contracts)

    connector.catalogue_config = catalogue
    connector.source_config = source_config
    connector.output = output
    connector.review = review
    workflow.catalogue = catalogue
    workflow.source_config = source_config
    workflow.tap_output = output
    workflow.review = review
    return workflow

