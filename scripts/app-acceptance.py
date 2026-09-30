"""Installed Stripe and SharePoint connectors against loopback API mocks (PB-064 phase 4).

Runs the full CLI path with the local provider: install, check, build, prepare,
discover, review, approve, run, unchanged retry, and a rejected credential that
commits nothing and names only its error code. The mocks follow the vendors'
documented APIs; no live Stripe account or Microsoft 365 tenant is used.
    INGESTRON_TEST_PROVIDER_GIT=../provider-local pnpm acceptance:apps
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile

import yaml
import pyarrow.parquet as parquet

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'test' / 'mocks'))
from loopback import loopback
from stripe_api import StripeApi
from graph_api import GraphApi, TENANT, CLIENT

CLI = Path(os.environ.get('INGESTRON_TEST_CLI', ROOT / 'node_modules/ingestron/build/cli/cli/index.js')).resolve()
PROVIDER_VERSION = os.environ.get('INGESTRON_TEST_PROVIDER_VERSION', '0.4.6')
PROVIDER_GIT = os.environ.get('INGESTRON_TEST_PROVIDER_GIT')
WORK = ROOT / 'build/app-acceptance'
shutil.rmtree(WORK, ignore_errors=True)
WORK.mkdir(parents=True)
STRIPE_KEY = 'rk_test_' + 'SyntheticAcceptance0123'
GRAPH_SECRET = 'graph-acceptance-' + 'secret'


def command(args, cwd, **kwargs):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, timeout=1200, **kwargs).stdout


def contract(name, columns):
    return {'apiVersion': 'v3.1.0', 'kind': 'DataContract', 'id': name, 'name': name, 'version': '1.0.0',
            'status': 'draft', 'schema': [{'name': name, 'logicalType': 'object', 'physicalType': 'table',
                                           'properties': columns}]}


def column(name, logical, physical, key=False):
    return {'name': name, 'logicalType': logical, 'physicalType': physical,
            **({'required': True, 'primaryKey': True} if key else {})}


def origin_of(source, tag, folder):
    """A throwaway Git origin holding the candidate tree at one tag."""
    for name in command(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], source).splitlines():
        path = source / name
        if path.is_file():
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, folder / name)
    for args in [['git', 'init', '-q'], ['git', 'add', '.'],
                 ['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                  'commit', '-qm', 'fixture'], ['git', 'tag', tag]]:
        command(args, folder)
    return folder


def accept(connector, settings, tables, env, api, handle, hosts, bad_env, code, secrets):
    project = WORK / connector
    project.mkdir()
    version = yaml.safe_load((ROOT / f'connectors/{connector}/connector.yaml').read_text())['version']
    config = {
        'apiVersion': 'ingestron.project/v1', 'id': f'{connector}_local',
        'packages': {'local': f'local@{PROVIDER_VERSION}', connector: f'{connector}@{version}'},
        'providers': {'configurations': {'local': {'package': 'local', 'binding': 'runtime'}}},
        'defaults': {'provider': 'local'},
        'environments': {'dev': {'apiVersion': 'ingestron.environment/v1', 'environment': 'dev',
                                 'bindings': {'runtime': {'kind': 'local'}}}},
        'connections': {'source': {'package': connector, 'sourceId': connector, 'tenantId': 'training',
                                   'settings': settings}},
        'flows': [{'apiVersion': 'ingestron.flow/v1', 'kind': 'ingestion', 'id': f'{connector}_flow',
                   'provider': 'local', 'ingestion': {'connection': 'source', 'execution': {'mode': 'local'}},
                   'tables': tables}],
    }
    (project / 'project.yaml').write_text(yaml.safe_dump(config, sort_keys=False))

    def cli(*args, ok=True, environment=env):
        proc = subprocess.run(['node', str(CLI), '--project', str(project), '--json', '--no-input', *args],
                              cwd=project, capture_output=True, text=True, timeout=1200,
                              env={**os.environ, **environment})
        result = json.loads(proc.stdout)
        assert result['ok'] == ok, (args, proc.stdout[-2000:])
        return result, proc.stdout + proc.stderr

    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        connectors_origin = origin_of(ROOT, f'{connector}-{version}', Path(a))
        provider = ['provider', 'install', f'ingestron/provider-local@{PROVIDER_VERSION}']
        if PROVIDER_GIT:
            provider += ['--from-git', str(origin_of(Path(PROVIDER_GIT).resolve(), PROVIDER_VERSION, Path(b)))]
        cli(*provider)
        cli('connector', 'install', f'ingestron/connectors/connectors/{connector}/connector.yaml@{version}',
            '--tag-prefix', f'{connector}-', '--from-git', str(connectors_origin))
    checked, _ = cli('check')
    reference = checked['result']['sources'][0]['selected']['reference']
    assert reference['maturity'] == 'preview', reference
    cli('build')
    cli('runtime', 'prepare')
    python = next((project / '.ingestron/runtimes').glob('*/bin/python'))
    site = Path(command([str(python), '-c', 'import sysconfig; print(sysconfig.get_paths()["purelib"])'],
                        project).strip())
    with loopback(site, handle, hosts):
        cli('run', '--action', 'discover')
        cli('run', '--action', 'review')
        cli('run', '--action', 'approve')
        run, _ = cli('run', '--run-id', 'run-001')
        counts = {t['stream']: t['rows'] for t in run['result']['result']['flows'][0]['tables']}
        outputs = sorted((project / 'build/generated/data').rglob('run-001/*.parquet'))
        before = {p: p.read_bytes() for p in outputs}
        cli('run', '--retry', 'run-001')
        assert before == {p: p.read_bytes() for p in outputs}
        _, text = cli('run', '--run-id', 'rejected', ok=False, environment=bad_env)
        assert code in text, text[-2000:]
        assert not any(s in text for s in secrets), 'secret echoed'
        assert not list((project / 'build/generated/data').rglob('rejected/*'))
    return counts, outputs


stripe = StripeApi(STRIPE_KEY)
stripe.load('customers', [{'id': f'cus_{i:03d}', 'object': 'customer', 'email': f'c{i}@example.invalid',
                           'balance': i * 10, 'created': 1_700_000_000 + i, 'livemode': False} for i in range(150)])
stripe.load('charges', [{'id': 'ch_1', 'object': 'charge', 'amount': 1250, 'currency': 'nzd',
                         'created': 1_700_000_000, 'livemode': False}])
stripe_counts, stripe_outputs = accept(
    'stripe', {'api_key': {'$secret': {'env': 'STRIPE_API_KEY'}}},
    {'customers': {'source': {'object': 'customers'},
                   'contract': contract('customers', [column('id', 'string', 'STRING', True),
                                                      column('email', 'string', 'STRING'),
                                                      column('balance', 'integer', 'BIGINT')])},
     'charges': {'source': {'object': 'charges'},
                 'contract': contract('charges', [column('id', 'string', 'STRING', True),
                                                  column('amount', 'integer', 'BIGINT'),
                                                  column('currency', 'string', 'STRING')])}},
    {'STRIPE_API_KEY': STRIPE_KEY}, stripe, lambda host, m, t, h, b: stripe.handle(m, t, h), {'api.stripe.com'},
    {'STRIPE_API_KEY': 'rk_test_' + 'WrongAcceptanceKey99'}, 'STRIPE_AUTH', [STRIPE_KEY, 'WrongAcceptanceKey99'])
assert stripe_counts == {'customers': 150, 'charges': 1}, stripe_counts
customers = next(p for p in stripe_outputs if 'customers' in str(p))
assert parquet.read_table(customers).num_rows == 150

graph = GraphApi(GRAPH_SECRET)
graph.put('drive-docs', 'retail/customers.csv', b'id,name\n1,Ada\n2,Grace\n')
graph.put('drive-docs', 'retail/orders/part-1.csv', b'order_id,amount\n10,12.50\n')
graph.put('drive-docs', 'retail/orders/part-2.csv', b'order_id,amount\n11,3.00\n12,7.25\n')
graph.put('drive-docs', 'retail/orders/readme.txt', b'ignored')
graph_counts, _ = accept(
    'sharepoint', {'tenant_id': TENANT, 'client_id': CLIENT,
                   'client_secret': {'$secret': {'env': 'GRAPH_CLIENT_SECRET'}},
                   'site': 'https://contoso.sharepoint.com/sites/finance'},
    {'customers': {'source': {'path': 'Shared Documents/retail/customers.csv', 'format': 'csv'},
                   'contract': contract('customers', [column('id', 'integer', 'BIGINT', True),
                                                      column('name', 'string', 'STRING')])},
     'orders': {'source': {'path': 'Shared Documents/retail/orders', 'format': 'csv'},
                'contract': contract('orders', [column('order_id', 'integer', 'BIGINT', True),
                                                column('amount', 'number', 'DECIMAL(10,2)')])}},
    {'GRAPH_CLIENT_SECRET': GRAPH_SECRET}, graph, graph.handle,
    {'login.microsoftonline.com', 'graph.microsoft.com', 'contoso.sharepoint.com'},
    {'GRAPH_CLIENT_SECRET': 'wrong-' + 'secret'}, 'GRAPH_AUTH', [GRAPH_SECRET, 'wrong-secret'])
assert graph_counts == {'customers': 2, 'orders': 3}, graph_counts

cli_version = json.loads((CLI.parents[3] / 'package.json').read_text())['version']
evidence = {'passed': True, 'cli': cli_version, 'provider': PROVIDER_VERSION,
            'stripe': {'rows': stripe_counts, 'pages': 2, 'rejected': 'STRIPE_AUTH'},
            'sharepoint': {'rows': graph_counts, 'folderFiles': 2, 'rejected': 'GRAPH_AUTH'},
            'retryUnchanged': True, 'transport': 'loopback mocks of the documented APIs', 'liveAccounts': False}
(WORK / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
print('Installed Stripe and SharePoint connectors: discovery, review, run, retry and rejected credentials passed')
