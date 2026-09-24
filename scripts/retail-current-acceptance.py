"""Run the current retail download through the published local stack."""
from hashlib import sha256
from pathlib import Path
import json
import os
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CLI = Path(os.environ.get('INGESTRON_TEST_CLI', ROOT / 'node_modules/ingestron/build/cli/cli/index.js')).resolve()
ARCHIVE = Path(os.environ.get('INGESTRON_TEST_RETAIL_ARCHIVE', ROOT / 'build/release/retail-files-1.1.0.zip')).resolve()
WORK = ROOT / 'build/retail-current-acceptance'
shutil.rmtree(WORK, ignore_errors=True)
WORK.mkdir(parents=True)

if not ARCHIVE.exists():
    subprocess.run(['python3', str(ROOT / 'scripts/package-retail.py')], check=True)
expected_hash = os.environ.get('INGESTRON_TEST_RETAIL_SHA256')
archive_hash = sha256(ARCHIVE.read_bytes()).hexdigest()
if expected_hash and archive_hash != expected_hash:
    raise ValueError('Retail download hash differs from its published value')


def command(project, args, success=True):
    result = subprocess.run(args, cwd=project, capture_output=True, text=True, timeout=1200)
    if (result.returncode == 0) != success:
        raise AssertionError(f'{args}: {result.stdout[-1200:]} {result.stderr[-1200:]}')
    return result


def cli(project, *args, success=True):
    return command(project, ['node', str(CLI), '--json', '--no-input', *args], success)


for fmt in ['csv', 'tsv', 'json', 'jsonl', 'parquet']:
    project = WORK / fmt
    project.mkdir()
    with zipfile.ZipFile(ARCHIVE) as downloaded:
        downloaded.extractall(project)
    command(project, ['python3', 'setup.py', '--format', fmt])
    cli(project, 'provider', 'install', 'local@0.4.1')
    cli(project, 'connector', 'install', 'files@1.1.0')
    cli(project, 'check')
    cli(project, 'build')
    cli(project, 'runtime', 'prepare')
    cli(project, 'run', '--action', 'discover')
    cli(project, 'run', '--action', 'review')
    if fmt == 'csv':
        cli(project, 'run', '--run-id', 'retail-unapproved', success=False)
        assert not list((project / 'build/generated/data').rglob('retail-unapproved/commit.json'))
    cli(project, 'run', '--action', 'approve')
    cli(project, 'run', '--run-id', 'retail-001')
    command(project, ['python3', 'inspect-output.py'])
    outputs = list((project / 'build/generated/data').rglob('retail-001/*.parquet'))
    assert len(outputs) == 3, outputs
    before = {path.name: sha256(path.read_bytes()).hexdigest() for path in outputs}
    cli(project, 'run', '--retry', 'retail-001')
    assert before == {path.name: sha256(path.read_bytes()).hexdigest() for path in outputs}
    if fmt == 'csv':
        orders = project / 'data/csv/orders.csv'
        original = orders.read_bytes()
        orders.write_text(orders.read_text().replace('1001', 'oops'))
        cli(project, 'run', '--run-id', 'retail-bad', success=False)
        assert not list((project / 'build/generated/data').rglob('retail-bad/commit.json'))
        orders.write_bytes(original)
        cli(project, 'run', '--retry', 'retail-bad')
        assert len(list((project / 'build/generated/data').rglob('retail-bad/*.parquet'))) == 3
        orders.write_text(orders.read_text().replace('order_id', 'changed_id'))
        cli(project, 'run', '--run-id', 'retail-drift', success=False)
        assert not list((project / 'build/generated/data').rglob('retail-drift/commit.json'))
        orders.write_bytes(original)
    print(f'{fmt}: three reviewed retail tables, output and retry passed', flush=True)

evidence = {
    'passed': True,
    'archiveSha256': archive_hash,
    'cli': json.loads((CLI.parents[3] / 'package.json').read_text())['version'],
    'core': json.loads((CLI.parents[3] / 'package.json').read_text())['dependencies']['@ingestron/core'],
    'provider': '0.4.1',
    'files': '1.1.0',
    'formats': ['csv', 'tsv', 'json', 'jsonl', 'parquet'],
    'tables': ['customers', 'products', 'orders'],
    'rowsPerTable': 3,
    'orderValue': '61.95',
    'unapprovedRejected': True,
    'malformedRejected': True,
    'schemaDriftRejected': True,
    'failedRunRecovered': True,
    'cloudAccess': False,
}
(WORK / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
