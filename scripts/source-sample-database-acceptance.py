"""Installed command/operation/MCP acceptance with a disposable loopback database."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'test' / 'containers'))
sys.path.insert(0, str(ROOT / 'runtime'))
from test_database_conformance import Engine, PASSWORD


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', required=True, help='Installed CLI JavaScript entry point')
    parser.add_argument('--harness', required=True, help='CLI repository sample acceptance script')
    parser.add_argument('--provider', required=True, help='Built local provider repository')
    parser.add_argument('--python', required=True, help='Python 3.12 used for clean locked preparation')
    parser.add_argument('--node', default='node')
    parser.add_argument('--out', required=True)
    parser.add_argument('--connector', choices=['postgresql', 'mysql'], default='postgresql')
    parser.add_argument('--workflow', choices=['sample', 'incremental'], default='sample')
    parser.add_argument('--image', help='Optional immutable Docker image reference')
    args = parser.parse_args()
    base = Path(args.out).resolve()
    base.mkdir(parents=True, exist_ok=True)
    if args.connector == 'postgresql':
        image = args.image or 'postgres:17-alpine@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24'
        port, env, settings = 5432, {'POSTGRES_PASSWORD': PASSWORD}, {'database': 'postgres', 'user': 'postgres'}
        schema, version_sql = 'public', 'SHOW server_version'
    else:
        image = args.image or 'mysql:8.4'
        port, env, settings = 3306, {'MYSQL_ROOT_PASSWORD': PASSWORD, 'MYSQL_DATABASE': 'synthetic', 'MYSQL_ROOT_HOST': '%'}, {'database': 'synthetic', 'user': 'root'}
        schema, version_sql = 'synthetic', 'SELECT VERSION()'
    engine = None
    try:
        engine = Engine(image, port, env, args.connector, settings)
        engine.run(f'CREATE TABLE {schema}.orders (id INTEGER PRIMARY KEY, label VARCHAR(100) NOT NULL)',
                   f"INSERT INTO {schema}.orders VALUES (1,'business-preview-only'),(2,'second'),(3,'third')")
        db = engine.connect()
        try:
            cursor = db.cursor(); cursor.execute(version_sql); version = str(cursor.fetchone()[0])
        finally:
            db.close()
        image_id = subprocess.check_output(['docker', 'inspect', '--format', '{{.Image}}', engine.id], text=True, timeout=30).strip()
        with tempfile.TemporaryDirectory(prefix='sample-db-', dir=base) as folder:
            fixture = Path(folder) / 'fixture.json'
            fixture.write_text(json.dumps({
                'settings': {'connection': {**engine.settings['connection'], 'password': {'$secret': {'env': 'SAMPLE_DB_PASSWORD'}}}},
                'source': {'schema': schema, 'table': 'orders'},
                'secrets': 'SAMPLE_DB_PASSWORD=' + PASSWORD + '\n',
            }))
            fixture.chmod(0o600)
            command = [args.node, str(Path(args.harness).resolve()), '--cli', str(Path(args.cli).resolve()),
                '--connectors', str(ROOT), '--provider', str(Path(args.provider).resolve()), '--connector', args.connector,
                '--fixture', str(fixture), '--python', args.python, '--out', str(base)]
            def run(extra=()):
                result = subprocess.run(command + list(extra), text=True, capture_output=True, timeout=1200)
                if result.returncode:
                    (base / 'synthetic-failure.log').write_text((result.stdout + result.stderr).replace(PASSWORD, '[redacted]'))
                    raise RuntimeError('Installed workflow acceptance failed; inspect the synthetic acceptance project')
                return json.loads(result.stdout)
            acceptance = run()
            if args.workflow == 'incremental':
                engine.run(f"INSERT INTO {schema}.orders VALUES (4,'unexpected-business-value')")
                run(['--phase','quality-failure','--base',acceptance['base']])
                engine.run(f"UPDATE {schema}.orders SET label='third' WHERE id=4")
                acceptance = run(['--phase','recovery','--base',acceptance['base']])
        proof = {'connector': args.connector, 'databaseVersion': version, 'image': image, 'imageId': image_id,
                 'binding': 'loopback only', 'cleanPreparation': True, 'acceptance': acceptance,
                 'checks': acceptance['checks'], 'status': 'passed'}
        path = base / (args.connector + '-installed-' + args.workflow + '.json')
        path.write_text(json.dumps(proof, indent=2) + '\n')
        print(json.dumps({'status':'passed','report':str(path),'connector':args.connector,'databaseVersion':version}))
    finally:
        if engine is not None: engine.stop()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Docker/driver exception text can contain credentials; retain only its class.
        print('Synthetic database sample acceptance failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
