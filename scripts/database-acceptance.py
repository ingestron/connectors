"""Installed PostgreSQL connector against a real PostgreSQL container (PB-064 phase 3).

Runs the full CLI path with the local provider: install, check, build, prepare,
discover, review, approve, run and retry, with a key rule checked before
commit. Synthetic data only; Docker required. Use the local stack CLI while
core is unreleased:
    INGESTRON_TEST_CLI=$(pnpm -s local-stack --print) pnpm acceptance:postgresql
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import time

import yaml
import pyarrow.parquet as parquet

ROOT = Path(__file__).resolve().parents[1]
CLI = Path(os.environ.get('INGESTRON_TEST_CLI', ROOT / 'node_modules/ingestron/build/cli/cli/index.js')).resolve()
VERSION = yaml.safe_load((ROOT / 'connectors/postgresql/connector.yaml').read_text())['version']
PROVIDER_VERSION = os.environ.get('INGESTRON_TEST_PROVIDER_VERSION', '0.4.5')
PASSWORD = 'Synthetic-Pass-2026'
WORK = ROOT / 'build/postgresql-acceptance'
shutil.rmtree(WORK, ignore_errors=True)
PROJECT = WORK / 'project'
PROJECT.mkdir(parents=True)


def command(args, cwd=PROJECT, **kwargs):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, timeout=1200, **kwargs).stdout


def cli(*args, ok=True):
    proc = subprocess.run(['node', str(CLI), '--project', str(PROJECT), '--json', '--no-input', *args],
                          cwd=PROJECT, capture_output=True, text=True, timeout=1200,
                          env={**os.environ, 'PG_READER_PASSWORD': PASSWORD})
    result = json.loads(proc.stdout)
    assert result['ok'] == ok, result
    return result


container = command(['docker', 'run', '-d', '--rm', '-p', '127.0.0.1::5432',
                     '-e', f'POSTGRES_PASSWORD={PASSWORD}', 'postgres:17-alpine'])
container = container.strip()
try:
    port = int(command(['docker', 'port', container, '5432']).strip().split(':')[-1])
    psql = lambda sql: command(['docker', 'exec', container, 'psql', '-U', 'postgres', '-v',
                                'ON_ERROR_STOP=1', '-c', sql])
    for _ in range(60):
        try:
            psql('SELECT 1')
            break
        except subprocess.CalledProcessError:
            time.sleep(2)
    psql('CREATE TABLE public.customers (id bigint NOT NULL, name text)')
    psql("INSERT INTO public.customers VALUES (1, 'Ada'), (2, 'Grace')")

    contract = {'apiVersion': 'v3.1.0', 'kind': 'DataContract', 'id': 'customers', 'name': 'Customers',
                'version': '1.0.0', 'status': 'draft',
                'schema': [{'name': 'customers', 'logicalType': 'object', 'physicalType': 'table',
                            'properties': [
                                {'name': 'id', 'logicalType': 'integer', 'physicalType': 'BIGINT',
                                 'required': True, 'primaryKey': True},
                                {'name': 'name', 'logicalType': 'string', 'physicalType': 'STRING'}]}]}
    project = {
        'apiVersion': 'ingestron.project/v1', 'id': 'postgres_local',
        'packages': {'local': f'local@{PROVIDER_VERSION}', 'postgresql': f'postgresql@{VERSION}'},
        'providers': {'configurations': {'local': {'package': 'local', 'binding': 'runtime'}}},
        'defaults': {'provider': 'local'},
        'environments': {'dev': {'apiVersion': 'ingestron.environment/v1', 'environment': 'dev',
                                'bindings': {'runtime': {'kind': 'local'}}}},
        'connections': {'sales': {'package': 'postgresql', 'sourceId': 'sales', 'tenantId': 'training',
                                  'settings': {'connection': {
                                      'host': '127.0.0.1', 'port': port, 'database': 'postgres',
                                      'user': 'postgres', 'tls': 'disable',
                                      'password': {'$secret': {'env': 'PG_READER_PASSWORD'}}}}}},
        'flows': [{'apiVersion': 'ingestron.flow/v1', 'kind': 'ingestion', 'id': 'sales_local',
                   'provider': 'local', 'ingestion': {'connection': 'sales', 'execution': {'mode': 'local'}},
                   'tables': {'customers': {'source': {'schema': 'public', 'table': 'customers'},
                                            'contract': contract}}}],
    }
    (PROJECT / 'project.yaml').write_text(yaml.safe_dump(project, sort_keys=False))

    with tempfile.TemporaryDirectory(prefix='postgresql-candidate-') as temporary:
        origin = Path(temporary)
        for name in command(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], ROOT).splitlines():
            source = ROOT / name
            if source.is_file():
                (origin / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, origin / name)
        for args in [['git', 'init', '-q'], ['git', 'add', '.'],
                     ['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                      'commit', '-qm', 'fixture'], ['git', 'tag', f'postgresql-{VERSION}']]:
            command(args, origin)
        cli('provider', 'install', f'ingestron/provider-local@{PROVIDER_VERSION}')
        cli('connector', 'install', f'ingestron/connectors/connectors/postgresql/connector.yaml@{VERSION}',
            '--tag-prefix', 'postgresql-', '--from-git', str(origin))
        checked = cli('check')
        assert checked['result']['sources'][0]['selected']['reference']['maturity'] == 'verified', checked
        cli('build')
        cli('runtime', 'prepare')
        cli('run', '--action', 'discover')
        cli('run', '--action', 'review')
        cli('run', '--action', 'approve')
        run = cli('run', '--run-id', 'pg-001')
        flow = run['result']['result']['flows'][0]
        assert {t['stream']: t['rows'] for t in flow['tables']} == {'customers': 2}, run
        assert all(r['passed'] for r in flow['quality']), flow['quality']
        [output] = (PROJECT / 'build/generated/data').rglob('pg-001/*.parquet')
        assert parquet.read_table(output).to_pylist() == [{'id': 1, 'name': 'Ada'}, {'id': 2, 'name': 'Grace'}]
        before = output.read_bytes()
        cli('run', '--retry', 'pg-001')
        assert output.read_bytes() == before
        psql("INSERT INTO public.customers VALUES (2, 'Duplicate')")
        failed = subprocess.run(['node', str(CLI), '--project', str(PROJECT), '--json', '--no-input',
                                 'run', '--run-id', 'pg-duplicate'], cwd=PROJECT, capture_output=True, text=True,
                                env={**os.environ, 'PG_READER_PASSWORD': PASSWORD})
        assert failed.returncode != 0 and 'customers.key-unique (1)' in failed.stdout, failed.stdout
        assert 'Duplicate' not in failed.stdout + failed.stderr and PASSWORD not in failed.stdout
        assert not list((PROJECT / 'build/generated/data').rglob('pg-duplicate/*'))
    evidence = {'passed': True, 'connector': f'postgresql@{VERSION}', 'provider': PROVIDER_VERSION,
                'cli': json.loads((CLI.parents[3] / 'package.json').read_text())['version'],
                'engine': 'postgres:17-alpine (local container)', 'rows': 2, 'retryUnchanged': True,
                'duplicateKeyRejectedWithoutCommit': True, 'cloudAccess': False}
    (WORK / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print('Installed PostgreSQL connector: discovery, review, run, retry and key rule passed against a local container')
finally:
    subprocess.run(['docker', 'rm', '-f', container], capture_output=True)
