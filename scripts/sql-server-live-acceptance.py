"""Optional bounded installed-package qualification against the private Northwind handout."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CLI = Path(os.environ.get('INGESTRON_TEST_CLI', str(ROOT / 'node_modules/ingestron/build/cli/cli/index.js'))).resolve()
HANDOUT = Path(os.environ['INGESTRON_SQL_HANDOUT'])
WORK = ROOT / 'build/sql-server-live'
PUBLIC = os.environ.get('INGESTRON_TEST_PUBLIC_SOURCE') == '1'
if WORK.exists(): shutil.rmtree(WORK)
WORK.mkdir(parents=True)
private = json.loads(HANDOUT.read_text())['sql']
environment = {**os.environ, 'SQL_READER_PASSWORD': private['password']}
transcript = []


def command(args, cwd, ok=True):
    result = subprocess.run(args, cwd=cwd, env=environment, capture_output=True, text=True, timeout=1200)
    # Keep the captured transcript local; credential values are never command arguments.
    transcript.append({'command': args, 'exit': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
    (WORK / 'transcript.json').write_text(json.dumps(transcript, indent=2) + '\n')
    assert (result.returncode == 0) == ok, result.stdout + result.stderr
    return result.stdout


def cli(*args, ok=True):
    return command(['node', str(CLI), '--no-input', *args], WORK, ok)


with tempfile.TemporaryDirectory() as tmp:
    origin = Path(tmp)
    for name in subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], cwd=ROOT, text=True).splitlines():
        path = ROOT / name
        if path.is_file():
            target = origin / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    for args in [['git', 'init', '-q'], ['git', 'add', '.'],
                 ['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'],
                 ['git', 'tag', 'sql-server-1.0.0']]:
        command(args, origin)
    text = (ROOT / 'examples/sql-server/project.template.yaml').read_text()
    for placeholder, value in {'__SQL_SERVER__': private['server'], '__SQL_DATABASE__': private['database'],
                               '__SQL_PORT__': private['port'], '__SQL_USERNAME__': private['user']}.items():
        text = text.replace(placeholder, json.dumps(value))
    (WORK / 'project.yaml').write_text(text)
    cli('plugin', 'install', 'ingestron/provider-local@0.4.1')
    cli('plugin', 'install', 'ingestron/connectors/connectors/sql-server/connector.yaml@1.0.0',
        '--tag-prefix', 'sql-server-', *([] if PUBLIC else ['--from-git', str(origin)]))
    cli('check')
    cli('build')
    cli('runtime', 'prepare')
    cli('run', '--action', 'discover')
    cli('run', '--action', 'review')
    cli('run', '--run-id', 'unapproved', ok=False)
    cli('run', '--action', 'approve')
    cli('run', '--run-id', 'northwind-001')
    outputs = list((WORK / 'build/generated/data').rglob('records.parquet'))
    assert len(outputs) == 1
    from subprocess import check_output
    runtime = next((WORK / '.ingestron/runtimes').glob('*/bin/python'))
    result = json.loads(check_output([str(runtime), '-c',
      'import json,pyarrow.parquet as pq,sys; t=pq.read_table(sys.argv[1]); print(json.dumps({"rows":t.num_rows,"columns":t.column_names,"priceType":str(t.schema.field("UnitPrice").type)}))',
      str(outputs[0])], text=True))
    assert result == {'rows': 77, 'columns': ['ProductID', 'ProductName', 'UnitPrice'], 'priceType': 'decimal128(19, 4)'}, result
    digest = hashlib.sha256(outputs[0].read_bytes()).hexdigest()
    cli('run', '--retry', 'northwind-001')
    assert hashlib.sha256(outputs[0].read_bytes()).hexdigest() == digest
    with (WORK / 'evidence.json').open('w') as f:
        json.dump({'passed': True, 'publicSource': PUBLIC, 'rows': result['rows'], 'priceType': result['priceType'],
                   'unapprovedRejected': True, 'retryVerified': True, 'auth': 'sql-password',
                   'source': 'private Northwind; no rows or credentials stored in Git'}, f, indent=2)
print('Installed SQL Server source and local provider accepted read-only Northwind snapshot')
