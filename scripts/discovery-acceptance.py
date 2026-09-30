"""Installed discovery per route (PB-064 phase 6).

1. Stripe (portable): tables with only a source; discover drafts contracts;
   the drafts then pass discover, review, approve and run.
2. Salesforce (native on ADF): discovered through the connection's portable
   package on the local provider.
3. PostgreSQL (container): real catalogue with a primary key and a skipped
   unsupported column.
4. A private SQL Server bridged to Databricks: ADF generates the metadata
   pipeline; its exported rows (synthetic here) become drafts through --from.
Loopback API mocks and a local container only; synthetic data.
    INGESTRON_TEST_CLI=$(pnpm -s local-stack --print) INGESTRON_TEST_PROVIDER_GIT=../provider-local \
      INGESTRON_TEST_ADF_GIT=../provider-adf-public pnpm acceptance:discovery
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'test' / 'mocks'))
from loopback import loopback
from stripe_api import StripeApi
from saas_api import SalesforceApi

CLI = Path(os.environ['INGESTRON_TEST_CLI']).resolve()
PROVIDER_GIT = Path(os.environ['INGESTRON_TEST_PROVIDER_GIT']).resolve()
ADF_GIT = Path(os.environ['INGESTRON_TEST_ADF_GIT']).resolve()
DATABRICKS_GIT = Path(os.environ.get('INGESTRON_TEST_DATABRICKS_GIT', ROOT.parent / 'provider-databricks-public')).resolve()
WORK = ROOT / 'build/discovery-acceptance'
shutil.rmtree(WORK, ignore_errors=True)
WORK.mkdir(parents=True)
STRIPE_KEY = 'rk_test_' + 'SyntheticDiscovery0123'
SF_SECRET = 'sf-client-' + 'secret'
PG_PASSWORD = 'Synthetic-Pass-2026'
ORIGINS = []


def command(args, cwd, **kwargs):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, timeout=1200, **kwargs).stdout


def origin_of(source, tag):
    folder = Path(tempfile.mkdtemp(prefix='origin-'))
    ORIGINS.append(folder)
    for name in command(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], source).splitlines():
        path = source / name
        if path.is_file():
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, folder / name)
    for args in [['git', 'init', '-q'], ['git', 'add', '.'],
                 ['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'f'],
                 ['git', 'tag', tag]]:
        command(args, folder)
    return folder


def version(connector):
    return yaml.safe_load((ROOT / f'connectors/{connector}/connector.yaml').read_text())['version']


def project(name, config):
    folder = WORK / name
    folder.mkdir()
    (folder / 'project.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
    return folder


def cli(folder, *args, ok=True, env=None):
    proc = subprocess.run(['node', str(CLI), '--project', str(folder), '--json', '--no-input', *args], cwd=folder,
                          capture_output=True, text=True, timeout=1200, env={**os.environ, **(env or {})})
    result = json.loads(proc.stdout)
    assert result['ok'] == ok, (args, proc.stdout[-3000:])
    return result, proc.stdout + proc.stderr


def install(folder, connector, provider_origin, adf_origin=None):
    cli(folder, 'provider', 'install', 'ingestron/provider-local@0.4.6', '--from-git', str(provider_origin))
    if adf_origin:
        cli(folder, 'provider', 'install', 'ingestron/provider-adf/plugin/provider.yaml@4.7.0', '--from-git', str(adf_origin))
    cli(folder, 'connector', 'install', f'ingestron/connectors/connectors/{connector}/connector.yaml@{version(connector)}',
        '--tag-prefix', f'{connector}-', '--from-git', str(connectors_origin[connector]))


def site_of(folder):
    python = next((folder / '.ingestron/runtimes').glob('*/bin/python'))
    return Path(command([str(python), '-c', 'import sysconfig; print(sysconfig.get_paths()["purelib"])'], folder).strip())


def base(pid, packages, connections, flows, extra_configs=None, bindings=None):
    return {'apiVersion': 'ingestron.project/v1', 'id': pid,
            'packages': {'local': 'local@0.4.6', **packages},
            'providers': {'configurations': {'local': {'package': 'local', 'binding': 'runtime'}, **(extra_configs or {})}},
            'defaults': {'provider': 'local'},
            'environments': {'dev': {'apiVersion': 'ingestron.environment/v1', 'environment': 'dev',
                                     'bindings': {'runtime': {'kind': 'local'}, **(bindings or {})}}},
            'connections': connections, 'flows': flows}


provider_origin = origin_of(PROVIDER_GIT, '0.4.6')
adf_origin = origin_of(ADF_GIT, '4.7.0')
connectors_origin = {c: origin_of(ROOT, f'{c}-{version(c)}') for c in ('stripe', 'salesforce', 'postgresql')}
evidence = {}

# 1. Stripe, portable, tables without contracts.
stripe = StripeApi(STRIPE_KEY)
# Stripe returns every field of an object, with null for empty values.
stripe.load('customers', [{'id': f'cus_{i}', 'object': 'customer', 'email': f'c{i}@example.invalid', 'balance': i,
                           'delinquent': False, 'created': 1_700_000_000 + i, 'livemode': False, 'name': None,
                           'description': None, 'phone': None, 'currency': 'nzd'} for i in range(3)])
folder = project('stripe', base('payments', {'stripe': f'stripe@{version("stripe")}'},
                                {'payments': {'package': 'stripe', 'sourceId': 'payments', 'tenantId': 'training',
                                              'settings': {'api_key': {'$secret': {'env': 'STRIPE_API_KEY'}}}}},
                                [{'apiVersion': 'ingestron.flow/v1', 'kind': 'ingestion', 'id': 'payments_local',
                                  'provider': 'local', 'ingestion': {'connection': 'payments', 'execution': {'mode': 'local'}},
                                  'tables': {'customers': {'source': {'object': 'customers'}}}}]))
install(folder, 'stripe', provider_origin)
# Prepare the runtime first: an invalid key stops before any request, so no traffic leaves the machine.
_, text = cli(folder, 'discover', '--flow', 'payments_local', ok=False, env={'STRIPE_API_KEY': 'invalid'})
with loopback(site_of(folder), lambda h, m, t, hd, b: stripe.handle(m, t, hd), {'api.stripe.com'}):
    result, _ = cli(folder, 'discover', '--flow', 'payments_local', '--accept-keys', env={'STRIPE_API_KEY': STRIPE_KEY})
    table = result['result']['tables'][0]
    draft = yaml.safe_load((folder / table['file']).read_text())
    names = {p['name']: p for p in draft['schema'][0]['properties']}
    assert names['id'].get('primaryKey') is True and names['balance']['physicalType'] == 'BIGINT', names
    assert names['delinquent']['physicalType'] == 'BOOLEAN' and len(names) == 11, names
    assert draft['status'] == 'draft'
    # The drafts are usable as reviewed contracts for a full run.
    config = yaml.safe_load((folder / 'project.yaml').read_text())
    config['flows'][0]['tables']['customers']['contract'] = {'$resolve': './' + table['file']}
    (folder / 'project.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
    env = {'STRIPE_API_KEY': STRIPE_KEY}
    cli(folder, 'check', env=env)
    cli(folder, 'build', env=env)
    cli(folder, 'runtime', 'prepare', env=env)
    cli(folder, 'run', '--action', 'discover', env=env)
    cli(folder, 'run', '--action', 'review', env=env)
    cli(folder, 'run', '--action', 'approve', env=env)
    run, _ = cli(folder, 'run', '--run-id', 'draft-001', env=env)
    rows = {t['stream']: t['rows'] for t in run['result']['result']['flows'][0]['tables']}
    assert rows == {'customers': 3}, rows
    _, again = cli(folder, 'discover', '--flow', 'payments_local', ok=False, env=env)
    assert 'exists' in again, 'drafts are never overwritten'
evidence['stripe'] = {'fields': len(names), 'key': 'id', 'draftRunRows': 3}

# 2. Salesforce, native on ADF, discovered through its portable package on the local provider.
salesforce = SalesforceApi('client-id', SF_SECRET)
salesforce.load('Account', {'Id': 'id', 'Name': 'string', 'AnnualRevenue': 'currency', 'NumberOfEmployees': 'int',
                            'IsDeleted': 'boolean', 'BillingAddress': 'address'}, [])
folder = project('salesforce', base(
    'crm', {'adf': 'ingestron/provider-adf/plugin/provider.yaml@4.7.0', 'salesforce': f'salesforce@{version("salesforce")}'},
    {'crm': {'kind': 'salesforce', 'route': 'native', 'binding': 'sf', 'package': 'salesforce', 'sourceId': 'crm',
             'tenantId': 'training',
             'settings': {'instance_url': 'https://acme.my.salesforce.com', 'client_id': 'client-id',
                          'client_secret': {'$secret': {'env': 'SF_CLIENT_SECRET'}}}}},
    [{'apiVersion': 'ingestron.flow/v1', 'kind': 'ingestion', 'id': 'crm_landing', 'provider': 'landing',
      'ingestion': {'connection': 'crm', 'standard': 'app-land@v1',
                    'target': {'linkedService': 'landing_adls', 'fileSystem': 'landing', 'path': 'crm'}},
      'tables': {'accounts': {'source': {'object': 'Account'}}}}],
    {'landing': {'package': 'adf', 'binding': 'factory'}},
    {'factory': {'kind': 'adf', 'factoryName': 'adf-crm-dev'}, 'sf': {'linkedService': 'crm_salesforce'}}))
install(folder, 'salesforce', provider_origin, adf_origin)
cli(folder, 'discover', '--flow', 'crm_landing', ok=False, env={'SF_CLIENT_SECRET': ''})
with loopback(site_of(folder), salesforce.handle, {'acme.my.salesforce.com'}):
    result, _ = cli(folder, 'discover', '--flow', 'crm_landing', env={'SF_CLIENT_SECRET': SF_SECRET})
    assert result['result']['route'] == 'native (via portable salesforce)', result['result']
    draft = yaml.safe_load((folder / result['result']['tables'][0]['file']).read_text())
    types = {p['name']: p['physicalType'] for p in draft['schema'][0]['properties']}
    assert types == {'Id': 'STRING', 'Name': 'STRING', 'AnnualRevenue': 'DECIMAL(38,9)', 'NumberOfEmployees': 'BIGINT',
                     'IsDeleted': 'BOOLEAN'}, types
    assert not any(p.get('primaryKey') for p in draft['schema'][0]['properties']), 'keys need --accept-keys'
evidence['salesforce'] = {'route': 'native via portable', 'fields': len(types), 'compoundSkipped': 'BillingAddress'}

# 3. PostgreSQL, real catalogue in a container.
container = command(['docker', 'run', '-d', '--rm', '-p', '127.0.0.1::5432', f'-ePOSTGRES_PASSWORD={PG_PASSWORD}',
                     'postgres:17-alpine'], ROOT).strip()
try:
    port = int(command(['docker', 'port', container, '5432'], ROOT).strip().split(':')[-1])
    psql = lambda sql: command(['docker', 'exec', container, 'psql', '-U', 'postgres', '-v', 'ON_ERROR_STOP=1',
                                '-c', sql], ROOT)
    for _ in range(60):
        try:
            psql('SELECT 1')
            break
        except subprocess.CalledProcessError:
            time.sleep(2)
    psql('CREATE TABLE public.customers (id bigint PRIMARY KEY, name text NOT NULL, amount numeric(10,2), payload jsonb)')
    folder = project('postgresql', base(
        'sales', {'postgresql': f'postgresql@{version("postgresql")}'},
        {'sales': {'package': 'postgresql', 'sourceId': 'sales', 'tenantId': 'training',
                   'settings': {'connection': {'host': '127.0.0.1', 'port': port, 'database': 'postgres',
                                               'user': 'postgres', 'tls': 'disable',
                                               'password': {'$secret': {'env': 'PG_PASSWORD'}}}}}},
        [{'apiVersion': 'ingestron.flow/v1', 'kind': 'ingestion', 'id': 'sales_local', 'provider': 'local',
          'ingestion': {'connection': 'sales', 'execution': {'mode': 'local'}},
          'tables': {'customers': {'source': {'schema': 'public', 'table': 'customers'}}}}]))
    install(folder, 'postgresql', provider_origin)
    result, _ = cli(folder, 'discover', '--flow', 'sales_local', '--accept-keys', env={'PG_PASSWORD': PG_PASSWORD})
    table = result['result']['tables'][0]
    draft = yaml.safe_load((folder / table['file']).read_text())
    props = {p['name']: p for p in draft['schema'][0]['properties']}
    assert props['id'] == {'name': 'id', 'logicalType': 'integer', 'physicalType': 'BIGINT', 'required': True,
                           'primaryKey': True}, props['id']
    assert props['amount']['physicalType'] == 'DECIMAL(10,2)' and props['name'].get('required') is True, props
    assert [s['name'] for s in table['skipped']] == ['payload'], table
    evidence['postgresql'] = {'fields': len(props), 'key': 'id', 'decimal': 'DECIMAL(10,2)', 'skipped': 'payload (jsonb)'}
finally:
    subprocess.run(['docker', 'rm', '-f', container], capture_output=True)

# 4. A private SQL Server bridged to Databricks: provider metadata discovery.
dbx_origin = origin_of(DATABRICKS_GIT, '3.7.0')
contract_less = {'customers': {'source': {'schema': 'dbo', 'table': 'Customers'}},
                 'orders': {'source': {'schema': 'dbo', 'table': 'Orders'}}}
config = base('retail', {'adf': 'ingestron/provider-adf/plugin/provider.yaml@4.7.0',
                         'databricks': 'ingestron/provider-databricks/plugin/provider.yaml@3.7.0'},
              {'erp': {'kind': 'sql-server', 'route': 'bridge', 'binding': 'erp_adf', 'sourceId': 'erp',
                       'tenantId': 'training',
                       'bridge': {'provider': 'landing', 'publisher': 'publisher',
                                  'landing': {'linkedService': 'landing_adls', 'fileSystem': 'landing', 'path': 'retail'},
                                  'handover': 'files', 'publication': {'maximumDropPercent': 50}}}},
              [{'apiVersion': 'ingestron.flow/v1', 'kind': 'ingestion', 'id': 'sales', 'provider': 'processing',
                'ingestion': {'connection': 'erp', 'standard': 'snapshot-with-history@v1', 'pipeline': 'sales',
                              'target': {'schema': 'current', 'historySchema': 'history'}},
                'tables': contract_less}],
              {'landing': {'package': 'adf', 'binding': 'factory'},
               'publisher': {'package': 'databricks', 'binding': 'engine'},
               'processing': {'package': 'databricks', 'binding': 'engine'}},
              {'factory': {'kind': 'adf', 'factoryName': 'adf-retail-dev'},
               'engine': {'kind': 'databricks', 'host': 'https://example.invalid', 'catalog': 'retail_dev'},
               'files': {'kind': 'adls', 'accountName': 'retailsampledev'},
               'erp_adf': {'linkedService': 'source_sql', 'variant': 'sql-server'}})
folder = project('bridge', config)
cli(folder, 'provider', 'install', 'ingestron/provider-adf/plugin/provider.yaml@4.7.0', '--from-git', str(adf_origin))
cli(folder, 'provider', 'install', 'ingestron/provider-databricks/plugin/provider.yaml@3.7.0', '--from-git', str(dbx_origin))
result, _ = cli(folder, 'discover', '--flow', 'sales')
assert result['result']['route'] == 'bridge metadata on landing', result['result']
files = set(result['result']['files'])
assert {'build/discovery/sales/template.json', 'build/discovery/sales/metadata-query.sql'} <= files, files
query = (folder / 'build/discovery/sales/metadata-query.sql').read_text()
assert "s.name IN ('dbo')" in query and "t.name IN ('Customers','Orders')" in query, query
# What the ADF pipeline's JSON sink would export (synthetic rows).
rows = [{'schema_name': 'dbo', 'table_name': t, 'column_name': c, 'ordinal_position': i + 1, 'data_type': d,
         'precision': p, 'scale': sc, 'max_length': 8, 'nullable': n, 'primary_key': k}
        for t, cols in {'Customers': [('CustomerID', 'int', 10, 0, False, True), ('Name', 'nvarchar', 0, 0, True, False)],
                        'Orders': [('OrderID', 'int', 10, 0, False, True), ('Freight', 'money', 19, 4, True, False),
                                   ('Shape', 'geography', 0, 0, True, False)]}.items()
        for i, (c, d, p, sc, n, k) in enumerate(cols)]
(folder / 'metadata.json').write_text(json.dumps(rows))
result, _ = cli(folder, 'discover', '--flow', 'sales', '--from', 'metadata.json', '--accept-keys')
tables = {t['table']: t for t in result['result']['tables']}
orders = yaml.safe_load((folder / tables['orders']['file']).read_text())['schema'][0]['properties']
assert [(p['name'], p['physicalType'], p.get('primaryKey', False)) for p in orders] == [
    ('OrderID', 'BIGINT', True), ('Freight', 'DECIMAL(19,4)', False)], orders
assert [s['name'] for s in tables['orders']['skipped']] == ['Shape'], tables['orders']
evidence['bridge'] = {'route': 'ADF metadata pipeline', 'draftsFrom': 'exported rows', 'skipped': 'Shape (geography)'}

(WORK / 'evidence.json').write_text(json.dumps({'passed': True, **evidence}, indent=2) + '\n')
for origin in ORIGINS:
    shutil.rmtree(origin, ignore_errors=True)
print('Installed discovery: portable, native via portable, database catalogue and provider metadata drafts passed')
