"""Exercise two contracted local files through installed core, CLI and provider."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import yaml
import pyarrow.parquet as parquet
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[1]
CLI = Path(os.environ.get('INGESTRON_TEST_CLI', ROOT / 'node_modules/ingestron/build/cli/cli/index.js')).resolve()
WORK = ROOT / 'build/files-table-acceptance'
shutil.rmtree(WORK, ignore_errors=True)
WORK.mkdir(parents=True)
PROJECT = WORK / 'project'
PROJECT.mkdir()


def command(args, cwd=PROJECT):
    return subprocess.check_output(args, cwd=cwd, text=True, timeout=1200)


def cli(*args):
    output = command(['node', str(CLI), '--project', str(PROJECT), '--json', '--no-input', *args])
    result = json.loads(output)
    assert result['ok'], result
    return result


def contract(name, properties):
    return {'apiVersion': 'v3.1.0', 'kind': 'DataContract', 'id': f'file-{name}',
            'name': f'File {name}', 'version': '1.0.0', 'status': 'draft',
            'schema': [{'name': name, 'logicalType': 'object', 'physicalType': 'table',
                        'properties': properties}]}


(PROJECT / 'customers.csv').write_text('customer_id,name\n1,Ada\n')
(PROJECT / 'orders.csv').write_text('order_id,amount\n1001,12.50\n')
project = {
    'apiVersion': 'ingestron.project/v1', 'id': 'files_multitable',
    'packages': {'local': 'local@0.4.1', 'files': 'files@1.1.0'},
    'providers': {'configurations': {'local': {'package': 'local', 'binding': 'runtime'}}},
    'defaults': {'provider': 'local'},
    'environments': {'dev': {'apiVersion': 'ingestron.environment/v1', 'environment': 'dev',
                            'bindings': {'runtime': {'kind': 'local'}}}},
    'connections': {'retail': {'package': 'files', 'sourceId': 'retail',
                              'tenantId': 'training', 'settings': {}}},
    'flows': [{'apiVersion': 'ingestron.flow/v1', 'kind': 'ingestion',
               'id': 'retail_files_local', 'provider': 'local',
               'ingestion': {'connection': 'retail', 'execution': {'mode': 'local'}},
               'tables': {
                   'customers': {'source': {'path': str((PROJECT / 'customers.csv').resolve()),
                                            'format': 'csv'},
                                 'contract': contract('customers', [
                                     {'name': 'customer_id', 'logicalType': 'integer',
                                      'physicalType': 'BIGINT', 'required': True},
                                     {'name': 'name', 'logicalType': 'string',
                                      'physicalType': 'STRING', 'required': True}])},
                   'orders': {'source': {'path': str((PROJECT / 'orders.csv').resolve()),
                                         'format': 'csv'},
                              'contract': contract('orders', [
                                  {'name': 'order_id', 'logicalType': 'integer',
                                   'physicalType': 'BIGINT', 'required': True},
                                  {'name': 'amount', 'logicalType': 'number',
                                   'physicalType': 'DECIMAL(10,2)', 'required': True}])},
               }}],
}
(PROJECT / 'project.yaml').write_text(yaml.safe_dump(project, sort_keys=False))

with tempfile.TemporaryDirectory(prefix='files-candidate-') as temporary:
    origin = Path(temporary)
    for name in command(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], ROOT).splitlines():
        source = ROOT / name
        if source.is_file():
            target = origin / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    for args in [['git', 'init', '-q'], ['git', 'add', '.'],
                 ['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                  'commit', '-qm', 'fixture'], ['git', 'tag', 'files-1.1.0']]:
        command(args, origin)
    cli('provider', 'install', 'ingestron/provider-local@0.4.1')
    cli('connector', 'install', 'ingestron/connectors/connectors/files/connector.yaml@1.1.0',
        '--tag-prefix', 'files-', '--from-git', str(origin))
    cli('check')
    cli('build')
    cli('runtime', 'prepare')
    cli('run', '--action', 'discover')
    cli('run', '--action', 'review')
    cli('run', '--action', 'approve')
    run = cli('run', '--run-id', 'files-001')
    assert {table['stream']: table['rows'] for table in run['result']['result']['flows'][0]['tables']} == {
        'customers': 1, 'orders': 1}, run
    snapshots = {path.stem: parquet.read_table(path).to_pylist()
                 for path in (PROJECT / 'build/generated/data').rglob('*.parquet')}
    assert snapshots == {'customers': [{'customer_id': 1, 'name': 'Ada'}],
                         'orders': [{'order_id': 1001, 'amount': Decimal('12.50')}]}, snapshots
    evidence = {'passed': True, 'cli': json.loads((CLI.parents[3] / 'package.json').read_text())['version'],
                'core': json.loads((CLI.parents[3] / 'package.json').read_text())['dependencies']['@ingestron/core'],
                'provider': '0.4.1', 'files': '1.1.0', 'tables': ['customers', 'orders'],
                'rowsPerTable': 1, 'cloudAccess': False}
    (WORK / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print('Installed two-file snapshot and ODCS-derived parser types passed')
