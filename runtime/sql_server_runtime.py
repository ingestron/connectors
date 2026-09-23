"""Multi-table SQL snapshots through the reviewed local execution boundary."""
import tempfile

import snapshot_runtime as workflow
from singer_bridge import canonical, digest
from sql_server_reader import scan


def source_config(config):
    workflow.check('projectLock' in config and 'sourceSettings' in config,
                   'SQL table bindings require a locked project')
    settings = workflow.resolve_secrets(config['sourceSettings'])
    workflow.check(set(settings) == {'connection'}, 'SQL connection settings must contain only connection')
    tables = config['projectLock']['tables']
    workflow.check(isinstance(tables, dict) and 1 <= len(tables) <= 100,
                   'Select 1–100 SQL tables')
    objects = {}
    for stream, table in tables.items():
        workflow.safe_name(stream)
        source = table['source']
        workflow.check(set(source) == {'schema', 'table', 'stream'} and source['stream'] == stream,
                       'SQL table source differs from its stream identity')
        columns = [column['name'] for column in table['columns']]
        workflow.check(1 <= len(columns) <= 500 and len(columns) == len(set(columns)),
                       'ODCS projection must select distinct columns')
        objects[stream] = {'schema': source['schema'], 'table': source['table'], 'columns': columns}
    return {'connection': settings['connection'], 'objects': objects}


def sql_output(executable, source, catalog, timeout, discover=False, protocol='singer'):
    workflow.check(set(source) == {'connection', 'objects'}, 'Invalid locked SQL source')
    if discover:
        streams = []
        for stream, obj in source['objects'].items():
            schema, _ = scan({'connection': source['connection'], 'object': obj})
            streams.append({'tap_stream_id': stream, 'stream': stream,
                            'schema': schema, 'metadata': []})
        yield canonical({'streams': streams}).encode()
        return
    selected = {s['tap_stream_id']: s for s in catalog['streams']
                if any(m.get('breadcrumb') == [] and m.get('metadata', {}).get('selected')
                       for m in s.get('metadata', []))}
    workflow.check(set(selected) == set(source['objects']), 'Reviewed SQL table selection changed')
    # Spool all rows before yielding any to the shared commit path. A failure in
    # the last table therefore cannot publish records from earlier tables.
    with tempfile.TemporaryFile(mode='w+b') as spool:
        schemas = []
        for stream, obj in source['objects'].items():
            def emit(row):
                line = (canonical({'type': 'RECORD', 'stream': stream, 'record': row}) + '\n').encode()
                workflow.check(len(line) <= 2_000_000, 'Record exceeds 2 MB')
                spool.write(line)
            schema, _ = scan({'connection': source['connection'], 'object': obj}, emit)
            workflow.check(digest(schema) == digest(selected[stream]['schema']),
                           'Source schema changed; rediscover and review')
            schemas.append((stream, schema))
        for stream, schema in schemas:
            yield (canonical({'type': 'SCHEMA', 'stream': stream, 'schema': schema}) + '\n').encode()
        spool.seek(0)
        yield from spool


base_review = workflow.review


def sql_review(discovery, selection, authored_contracts=None):
    # Stream IDs are the flow's table keys, frozen in projectLock and discovery.
    streams = [s['tap_stream_id'] for s in discovery['catalog']['streams']]
    workflow.check(set(selection) == set(streams) and len(streams) == len(set(streams)),
                   'Review every table selected by the locked ingestion flow')
    workflow.CATALOGUE[0]['supportedStreams'] = streams
    return base_review(discovery, selection, authored_contracts)


workflow.source_config = source_config
workflow.tap_output = sql_output
workflow.review = sql_review
runtime_identity = workflow.runtime_identity

if __name__ == '__main__':
    workflow.main()
