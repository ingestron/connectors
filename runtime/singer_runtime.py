"""Explicit customer-side execution. The Ingestron compiler never imports this file."""
from __future__ import annotations
import argparse
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
from decimal import Decimal
from singer_bridge import canonical, digest, file_digest, safe_name, arrow_type, snapshot

VERSION = '0.3.0'
CATALOGUE = json.loads(Path(__file__).with_name('connectors.json').read_text())
CONNECTORS = {row['id']:(row['package'],row['version'],row['executable'],row['licence'])
              for row in CATALOGUE if row['prepared']}



def check(condition, message):
    if not condition:
        raise ValueError(message)


def load(path):
    check(Path(path).stat().st_size <= 2_000_000, 'Configuration/catalogue exceeds 2 MB')
    return json.loads(Path(path).read_text())


def field_from_column(type_name, required):
    type_name = str(type_name).upper()
    types = {'STRING':'string','BIGINT':'integer','INT':'integer','INTEGER':'integer','SMALLINT':'integer','DOUBLE':'number','FLOAT':'number','BOOLEAN':'boolean'}
    decimal = re.fullmatch(r'DECIMAL\((\d+),\s*(\d+)\)', type_name)
    check(type_name in types or decimal, 'Unsupported ODCS projection type')
    if decimal: return {'type':'decimal','precision':int(decimal[1]),'scale':int(decimal[2]),'nullable':not required}
    return {'type':types[type_name],'nullable':not required}


def project_selection(project):
    if 'tables' not in project: return project['selection']
    return {table['source']['stream']:{'name':name,'fields':{column['name']:field_from_column(column['type'],column['required']) for column in table['columns']}} for name,table in project['tables'].items()}


def project_contracts(project):
    if 'tables' not in project: return None
    return {name:table['contract'] for name,table in project['tables'].items()}


def runtime_identity(config, folder):
    check(sys.version_info[:2] == (3,12) and os.name == 'posix', 'Use Python 3.12 on POSIX')
    check(config.get('apiVersion') == 'ingestron.singer/v1', 'Unsupported runtime configuration')
    check(config.get('mode') == 'customer-operated', 'Only customer-operated execution is implemented')
    check(config.get('connector') in CONNECTORS, 'Unknown exact connector')
    check(set(config) <= {'apiVersion','mode','connector','sourceId','tenantId','configEnv','timeoutSeconds','reviewFile','sourceSettings','projectLock'}, 'Unsupported runtime setting')
    safe_name(config['sourceId']); safe_name(config['tenantId'])
    check(config.get('reviewFile') == 'review.json', 'Use the reviewed bundle review.json')
    check(type(config.get('timeoutSeconds')) is int and 1 <= config['timeoutSeconds'] <= 604800, 'Invalid source timeout')
    check(re.fullmatch(r'[A-Z][A-Z0-9_]{0,100}', config.get('configEnv', '')), 'Invalid configuration environment reference')
    package, version, executable, licence = CONNECTORS[config['connector']]
    check(metadata.version(package) == version, 'Installed connector version differs from selection')
    lock = folder / 'requirements.lock.txt'
    from singer_inventory import inventory
    inventory(lock)
    # Original runtime assets and upstream distribution hashes contribute to identity.
    provenance = load(folder / 'runtime.lock.json')
    check(provenance['connector'] == config['connector'], 'Runtime lock connector mismatch')
    for filename, expected in provenance['files'].items():
        check('/' not in filename and '\\' not in filename and filename not in ('.','..'), 'Invalid runtime asset')
        check(file_digest(folder / filename) == expected, 'Runtime asset differs from prepared bundle')
    check(('sourceSettings' in config) == ('projectLock' in config), 'Project settings require provenance')
    project_identity = {}
    if 'sourceSettings' in config:
        import jsonschema
        jsonschema.Draft202012Validator(load(folder / 'settings.schema.json')).validate(config['sourceSettings'])
    if 'projectLock' in config:
        project = dict(config['projectLock'])
        check(project.get('runtimeContract') == 'ingestron.snapshot/python/v1', 'Unsupported project runtime contract')
        expected = project.pop('specificationSha256')
        check(digest(project) == expected, 'Project specification hash mismatch')
        check(load(folder / 'project-connection.lock.json') == config['projectLock'], 'Project lock changed')
        check(config['sourceSettings'] == project['settings'], 'Connection settings differ from project lock')
        check(config['connector'] == project['connector'].split(':',1)[-1] and config['sourceId'] == project['sourceId'] and config['tenantId'] == project['tenantId'] and config['timeoutSeconds'] == project['timeoutSeconds'], 'Runtime differs from project lock')
        check(load(folder / 'selection.json') == project_selection(project), 'Selection differs from project lock')
        check(project['execution'] == {'mode': 'local'}, 'Only local execution is supported')
        project_identity = {'projectSpecSha256': expected}
    return {**project_identity, 'bridgeVersion': VERSION, 'connector': config['connector'], 'licence': licence,
            'sourceId': config['sourceId'], 'tenantId': config['tenantId'],
            'runtimeLockSha256': digest(provenance)}


def tap_output(executable, source_config, catalog, timeout, discover=False, protocol="singer"):
    """No shell, bounded lines, private config, discarded upstream diagnostics.

    Nonzero exit and timeout are failures even after apparently complete records.
    A consumer that stops early terminates the entire upstream process group.
    """
    with tempfile.TemporaryDirectory(prefix='ingestron-tap-') as temp:
        directory = Path(temp)
        config_path = directory / 'config.json'
        config_path.write_text(canonical(source_config)); config_path.chmod(0o600)
        check(protocol == 'singer', 'Unsupported connector protocol')
        args = [str(executable), '--config', str(config_path)]
        if discover:
            args += ['--discover']
        else:
            path = directory / 'catalog.json'; path.write_text(canonical(catalog))
            args += ['--catalog', str(path)]
        # Avoid ambient tap configuration, PYTHONPATH and unrelated credentials.
        env = {key: os.environ[key] for key in ('PATH','LANG','SYSTEMROOT','SSL_CERT_FILE') if key in os.environ}
        env['HOME'] = temp
        env['PYTHONNOUSERSITE'] = '1'
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   stdin=subprocess.DEVNULL, env=env, cwd=temp, start_new_session=True)
        expired = threading.Event()
        def kill():
            expired.set()
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        timer = threading.Timer(timeout, kill); timer.start()
        try:
            while True:
                line = process.stdout.readline(16_000_001)
                if not line: break
                check(len(line) <= 16_000_000, 'Upstream message exceeds 16 MB')
                yield line
            code = process.wait()
            check(not expired.is_set(), 'Upstream timeout')
            check(code == 0, 'Upstream process failed; diagnostics withheld')
        finally:
            timer.cancel()
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            process.wait(); process.stdout.close()


def resolve_secrets(value):
    """Resolve only in the customer runtime, never during compilation/replay."""
    if isinstance(value, list): return [resolve_secrets(item) for item in value]
    if not isinstance(value, dict): return value
    if '$secret' not in value: return {key: resolve_secrets(child) for key,child in value.items()}
    check(set(value) == {'$secret'} and isinstance(value['$secret'], dict), 'Invalid secret reference')
    ref = value['$secret']
    if set(ref) == {'env'}:
        check(isinstance(ref['env'], str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', ref['env']), 'Invalid secret environment name')
        result = os.environ.get(ref['env'])
    else:
        raise ValueError('This local release supports environment secret references only')
    check(isinstance(result, str) and 0 < len(result) <= 1_000_000, 'Missing or oversized referenced secret')
    return result


def source_config(config):
    if 'sourceSettings' in config:
        value = resolve_secrets(config['sourceSettings'])
    else:
        raw = os.environ.get(config['configEnv'])
        check(raw is not None and len(raw) <= 1_000_000, 'Set the referenced configuration environment variable')
        value = json.loads(raw)
    check(isinstance(value, dict), 'Tap configuration must be an object')
    # Stream maps can mutate reviewed data/schema; this preview does not implement them.
    check(not any(k in value for k in ('stream_maps','stream_map_config','flattening_enabled','flattening_max_depth')), 'Tap transformations are not supported')
    if config['connector'].startswith('github@'):
        check(value.get('api_url_base', 'https://api.github.com') == 'https://api.github.com', 'This variant is GitHub.com only; authentication has a hardcoded public endpoint')
        check(isinstance(value.get('auth_token'), str) and value['auth_token'] and not any(value.get(k) for k in ('auth_app_keys','org_auth_app_keys')), 'GitHub preview requires a personal access token')
        value['skip_parent_streams'] = True
    return value


def discover(config, folder):
    identity = runtime_identity(config, folder)
    executable = Path(sys.executable).parent / CONNECTORS[config['connector']][2]
    catalog = read_catalog(executable, source_config(config), config['timeoutSeconds'], protocol_for(config))
    return {'apiVersion':'ingestron.singer-discovery/v1','identity':identity,'catalog':catalog,'applied':False}


def protocol_for(config):
    return next(row.get("protocol", "singer") for row in CATALOGUE if row["id"] == config["connector"])


def read_catalog(executable, source, timeout, protocol="singer"):
    chunks, count = [], 0
    for chunk in tap_output(executable, source, None, timeout, True, protocol):
        count += len(chunk); check(count <= 2_000_000, 'Discovery exceeds 2 MB; narrow source configuration')
        chunks.append(chunk)
    catalog = json.loads(b''.join(chunks))
    check(isinstance(catalog.get('streams'), list), 'Discovery did not return a Singer catalogue')
    return catalog


def review(discovery, selection, authored_contracts=None):
    """An explicit projection becomes both the runtime contract and ODCS tables."""
    check(discovery.get('apiVersion') == 'ingestron.singer-discovery/v1', 'Use discovery evidence')
    check(isinstance(selection, dict) and 1 <= len(selection) <= 100, 'Select 1–100 stream IDs')
    catalog = json.loads(canonical(discovery['catalog']))
    streams = {s['tap_stream_id']: s for s in catalog['streams']}
    check(len(streams) == len(catalog['streams']), 'Duplicate stream identity')
    connector = discovery.get('identity', {}).get('connector')
    if connector in CONNECTORS:
        supported = next(row['supportedStreams'] for row in CATALOGUE if row['id'] == connector)
        check(set(selection) <= set(supported), 'Stream is not supported by this release')
    tables, contracts, names = {}, {}, set()
    for stream_id, spec in selection.items():
        check(stream_id in streams, 'Selected stream absent')
        stream = streams[stream_id]
        name = safe_name(spec['name'])
        check(name not in names and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name), 'Duplicate/invalid table name'); names.add(name)
        fields = spec['fields']
        check(isinstance(fields, dict) and 1 <= len(fields) <= 500, 'Select 1–500 fields')
        properties = stream['schema'].get('properties', {})
        odcs = []
        for field, shape in sorted(fields.items()):
            check(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', field) and field in properties, 'Invalid/missing selected field')
            check(set(shape) <= {'type','nullable','precision','scale'}, 'Unsupported projection property')
            check(type(shape.get('nullable')) is bool, 'Explicit nullable boolean required')
            arrow_type(shape)
            kind = shape['type']
            if kind == 'decimal':
                check(type(shape.get('precision')) is int and type(shape.get('scale')) is int and 1 <= shape['precision'] <= 38 and 0 <= shape['scale'] <= shape['precision'], 'Invalid decimal precision/scale')
                physical = f"DECIMAL({shape['precision']},{shape['scale']})"
            else:
                check('precision' not in shape and 'scale' not in shape, 'Precision/scale apply only to decimal')
                physical = {'string':'STRING','integer':'BIGINT','boolean':'BOOLEAN','number':'DOUBLE','json':'STRING'}[kind]
            odcs.append({'name':field,'logicalType': {'json':'string','decimal':'number'}.get(kind,kind),
                         'physicalType':physical,'required':not shape['nullable'],
                         'description':'Canonical structured JSON; missing and null collapse.' if kind == 'json' else 'Explicit reviewed source projection; no business key inferred.'})
        wire_name = stream.get('stream') or stream_id
        check(wire_name not in tables, 'Duplicate Singer wire stream name')
        safe_name(wire_name)
        tables[wire_name] = {'schema_sha256':digest(stream['schema']), 'fields':fields}
        contracts[name] = {'apiVersion':'v3.1.0','kind':'DataContract','id':name,'name':name,
                           'version':'1.0.0','status':'draft','schema':[{'name':name,'physicalName':wire_name,
                           'logicalType':'object','physicalType':'table','properties':odcs}]}
    for stream in catalog['streams']:
        selected = stream['tap_stream_id'] in selection
        stream['replication_method'] = 'FULL_TABLE'
        stream.pop('replication_key', None)
        entries = stream.setdefault('metadata', [])
        root = next((m for m in entries if m['breadcrumb'] == []), None)
        if root is None:
            root = {'breadcrumb':[], 'metadata':{}}; entries.append(root)
        root['metadata'].update({'selected':selected, 'replication-method':'FULL_TABLE'})
        root['metadata'].pop('replication-key', None)
        # Preserve full source schema for drift checks. Projection happens at the bridge;
        # upstream may need additional automatic keys/parent fields for extraction.
        for item in entries:
            if item['breadcrumb']: item['metadata']['selected'] = selected
    if authored_contracts is not None:
        check(set(authored_contracts) == set(contracts), 'ODCS table identities differ')
        for name, contract in authored_contracts.items():
            check(len(contract['schema']) == 1, 'One ODCS schema per table required')
            actual = {p.get('physicalName', p['name']): field_from_column(p.get('physicalType') or {'string':'STRING','integer':'BIGINT','number':'DOUBLE','boolean':'BOOLEAN'}.get(p['logicalType']), p.get('required',False)) for p in contract['schema'][0]['properties']}
            expected = next(spec['fields'] for spec in selection.values() if spec['name'] == name)
            check(actual == expected, 'ODCS fields differ from extraction projection')
        contracts = authored_contracts
    return {'apiVersion':'ingestron.singer-review/v1','status':'draft','identity':discovery['identity'],
            'catalog':catalog,'projection':tables,'contracts':contracts,'selection':selection, **({'authoredContracts':authored_contracts} if authored_contracts is not None else {})}


def accepted(bundle, identity):
    check(bundle.get('status') == 'approved' and bundle.get('apiVersion') == 'ingestron.singer-review/v1', 'Review bundle must be explicitly approved')
    check(bundle['identity'] == identity, 'Discovery runtime/source identity differs')
    rebuilt = review({'apiVersion':'ingestron.singer-discovery/v1','identity':identity,'catalog':bundle['catalog']}, bundle['selection'], bundle.get('authoredContracts'))
    check(rebuilt['projection'] == bundle['projection'] and rebuilt['contracts'] == bundle['contracts'] and rebuilt['catalog'] == bundle['catalog'], 'Review artefacts disagree; regenerate from selection')
    return bundle['projection']


def execute(config, folder, output, run_id, raw_config=None):
    identity = runtime_identity(config, folder)
    bundle = load(folder / config['reviewFile'])
    contract = accepted(bundle, identity)
    if 'projectLock' in config:
        check(bundle['selection'] == project_selection(config['projectLock']), 'Review differs from project selection')
        if 'tables' in config['projectLock']: check(bundle['contracts'] == project_contracts(config['projectLock']), 'Review differs from authored ODCS contracts')
    namespace = digest({'source':config['sourceId'],'tenant':config['tenantId']})
    executable = Path(sys.executable).parent / CONNECTORS[config['connector']][2]
    def messages():
        source = raw_config if raw_config is not None else source_config(config)
        protocol = protocol_for(config)
        fresh = read_catalog(executable, source, config['timeoutSeconds'], protocol)
        schemas = {s['tap_stream_id']:s['schema'] for s in fresh['streams']}
        for selected in bundle['catalog']['streams']:
            if selected['tap_stream_id'] in bundle['selection']:
                check(digest(schemas.get(selected['tap_stream_id'])) == digest(selected['schema']), 'Source schema changed; rediscover and review')
        catalog = bundle['catalog']
        lines = tap_output(executable, source, catalog, config['timeoutSeconds'])
        for line in lines:
            # Singer serialises decimal values as JSON numbers: preserve them exactly.
            value = json.loads(line, parse_float=Decimal)
            if value.get('type') == 'RECORD':
                wire = value.get('stream')
                if wire in contract:
                    for key, shape in contract[wire]['fields'].items():
                        if shape['type'] == 'number' and isinstance(value['record'].get(key), Decimal):
                            value['record'][key] = float(value['record'][key])
            elif value.get('type') != 'STATE':
                # Schema numeric metadata uses canonical standard JSON.
                value = json.loads(line)
            yield value
    return snapshot(output, namespace, run_id, contract, {**identity,'reviewSha256':digest(bundle)}, messages)


def main():
    parser = argparse.ArgumentParser(description='Customer-operated Singer preview')
    parser.add_argument('action', choices=['discover','review','approve','run'])
    parser.add_argument('--config', default='connector.json')
    parser.add_argument('--selection')
    parser.add_argument('--discovery', default='discovery.json')
    parser.add_argument('--output')
    parser.add_argument('--run-id')
    args = parser.parse_args()
    try:
        folder = Path(args.config).resolve().parent
        config = load(args.config)
        if args.action == 'discover': result = discover(config, folder)
        elif args.action == 'review':
            discovered = load(args.discovery)
            check(discovered['identity'] == runtime_identity(config, folder), 'Discovery differs from current project/runtime')
            result = review(discovered, load(args.selection or folder / 'selection.json'), project_contracts(config.get('projectLock',{})))
        elif args.action == 'approve':
            target = folder / config['reviewFile']
            result = load(target)
            identity = runtime_identity(config, folder)
            check(result['identity'] == identity and result['status'] == 'draft', 'Approve the current draft only')
            if 'projectLock' in config: check(result['selection'] == project_selection(config['projectLock']), 'Review differs from project selection')
            if 'tables' in config.get('projectLock',{}): check(result['contracts'] == project_contracts(config['projectLock']), 'Review differs from authored ODCS contracts')
            result['status'] = 'approved'
            accepted(result, identity)
            temporary = target.with_suffix('.approved.tmp')
            with temporary.open('x') as output: output.write(canonical(result)+'\n')
            temporary.replace(target)
            print(canonical({'status':'Succeeded','approved':True})); return
        else:
            check(args.output is not None, 'Explicit output path required')
            check(args.run_id is not None, 'Explicit stable run ID required')
            receipt = execute(config, folder, args.output, args.run_id)
            print(canonical({'status':'Succeeded','identity':receipt['identity'],'tables':receipt['tables']})); return
        check(args.output is not None, 'Explicit output path required')
        # Never overwrite an existing discovery/review file silently.
        with Path(args.output).open('x') as target: target.write(canonical(result)+'\n')
        print(canonical({'status':'Succeeded','applied':False}))
    except Exception:
        print(canonical({'status':'Failed','error':'Connector operation failed. Check configuration, frozen runtime, review, source access and committed output; upstream details withheld.'}))
        raise SystemExit(1) from None

if __name__ == '__main__': main()
