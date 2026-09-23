"""Several contracted local files through the reviewed snapshot workflow."""
import tempfile

import snapshot_runtime as workflow
from files_reader import scan
from singer_bridge import canonical, digest


def parser_kind(native_type):
    kind = native_type.upper()
    if kind == 'STRING': return 'string'
    if kind in ('BIGINT', 'INT', 'INTEGER', 'SMALLINT'): return 'integer'
    if kind.startswith('DECIMAL('): return 'decimal'
    if kind in ('DOUBLE', 'FLOAT'): return 'number'
    if kind == 'BOOLEAN': return 'boolean'
    raise ValueError('File input does not support the contracted column type')


def source_config(config):
    workflow.check('projectLock' in config and 'sourceSettings' in config,
                   'File table bindings require a locked project')
    workflow.check(config['sourceSettings'] == {},
                   'Local file connection settings must be empty')
    tables = config['projectLock']['tables']
    workflow.check(isinstance(tables, dict) and 1 <= len(tables) <= 100,
                   'Select 1–100 file tables')
    files = {}
    for stream, table in tables.items():
        workflow.safe_name(stream)
        source = table['source']
        workflow.check(set(source) == {'path', 'format', 'stream'} and source['stream'] == stream,
                       'File table source differs from its stream identity')
        columns = table['columns']
        workflow.check(isinstance(columns, list) and 1 <= len(columns) <= 500,
                       'ODCS contract must select 1–500 file columns')
        types = {column['name']: parser_kind(column['type']) for column in columns}
        workflow.check(len(types) == len(columns), 'ODCS file columns must be distinct')
        files[stream] = {'path': source['path'], 'format': source['format'], 'types': types}
    return {'files': files}


def file_output(executable, source, catalog, timeout, discover=False, protocol='singer'):
    workflow.check(set(source) == {'files'}, 'Invalid locked file source')
    if discover:
        streams = []
        for stream, settings in source['files'].items():
            schema, _ = scan(settings)
            streams.append({'tap_stream_id': stream, 'stream': stream,
                            'schema': schema, 'metadata': []})
        yield canonical({'streams': streams}).encode()
        return
    selected = {s['tap_stream_id']: s for s in catalog['streams']
                if any(m.get('breadcrumb') == [] and m.get('metadata', {}).get('selected')
                       for m in s.get('metadata', []))}
    workflow.check(set(selected) == set(source['files']), 'Reviewed file table selection changed')
    # Validate and spool every file before yielding records for any table.
    with tempfile.TemporaryFile(mode='w+b') as spool:
        schemas = []
        for stream, settings in source['files'].items():
            def emit(row):
                line = (canonical({'type': 'RECORD', 'stream': stream, 'record': row}) + '\n').encode()
                workflow.check(len(line) <= 2_000_000, 'Record exceeds 2 MB')
                spool.write(line)
            schema, _ = scan(settings, emit)
            workflow.check(digest(schema) == digest(selected[stream]['schema']),
                           'Source schema changed; rediscover and review')
            schemas.append((stream, schema))
        for stream, schema in schemas:
            yield (canonical({'type': 'SCHEMA', 'stream': stream, 'schema': schema}) + '\n').encode()
        spool.seek(0)
        yield from spool


base_review = workflow.review


def file_review(discovery, selection, authored_contracts=None):
    streams = [s['tap_stream_id'] for s in discovery['catalog']['streams']]
    workflow.check(set(selection) == set(streams) and len(streams) == len(set(streams)),
                   'Review every table selected by the locked file flow')
    workflow.CATALOGUE[0]['supportedStreams'] = streams
    return base_review(discovery, selection, authored_contracts)


workflow.source_config = source_config
workflow.tap_output = file_output
workflow.review = file_review
runtime_identity = workflow.runtime_identity
if __name__ == '__main__': workflow.main()
