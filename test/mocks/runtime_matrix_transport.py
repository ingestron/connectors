"""Installed-matrix DB-API/OpenSSH transport stand-ins; never runtime assets.

The connector's validation, catalogue, projection, sample, conversion and snapshot
code remain installed and unmodified. This does not qualify a database driver,
database engine, SSH server, TLS implementation or real account.
"""
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import re
import sys
import types

SOURCE = os.environ.get('INGESTRON_MATRIX_SOURCE') or json.loads(
    Path(os.environ['INGESTRON_MATRIX_TRANSPORT_STATE']).read_text()).get('source')
DATABASES = {'postgresql', 'mysql', 'oracle', 'sql-server'}


def state():
    path = Path(os.environ['INGESTRON_MATRIX_TRANSPORT_STATE'])
    assert path.is_absolute() and path.is_file() and not path.is_symlink()
    return json.loads(path.read_text())


def observed(kind):
    path = Path(os.environ['INGESTRON_MATRIX_TRANSPORT_STATE']).with_suffix('.requests.jsonl')
    with path.open('a') as stream:
        stream.write(json.dumps({'source': SOURCE, 'kind': kind}) + '\n')


class Database:
    def cursor(self):
        return Cursor()

    def close(self):
        pass


class Cursor:
    def execute(self, query, parameters=None):
        assert isinstance(query, str)
        sql = ' '.join(query.lower().split())
        self.position = 0
        if sql in ('select 1', 'select 1 from dual'):
            self.rows = [(1,)]
            observed('test')
        elif 'information_schema.tables' in sql or 'from all_tables' in sql or ('select top' in sql and 'from sys.tables t' in sql):
            assert parameters and len(parameters) >= 6
            schema, table = ('RETAIL', 'ORDERS') if SOURCE == 'oracle' else ('dbo', 'Orders') if SOURCE == 'sql-server' else ('public', 'orders') if SOURCE == 'postgresql' else ('retail', 'orders')
            self.rows = [(schema, table)]
            observed('inventory')
        elif 'information_schema.columns' in sql or 'all_tab_columns' in sql or 'sys.columns' in sql:
            assert parameters and len(parameters) == 2
            integer, string = ('NUMBER', 'VARCHAR2') if SOURCE == 'oracle' else ('bigint', 'character varying') if SOURCE == 'postgresql' else ('bigint', 'varchar')
            nullable = 'N' if SOURCE == 'oracle' else False if SOURCE == 'sql-server' else 'NO'
            self.rows = [('id', integer, 18, 0, nullable), ('label', string, None, None, nullable), ('unused', string, None, None, nullable)]
            if SOURCE == 'sql-server' and 'is_primary_key' in sql:
                self.rows = [(*row, index == 0) for index, row in enumerate(self.rows)]
            observed('metadata')
        elif 'key_column_usage' in sql or 'all_constraints' in sql:
            assert parameters and len(parameters) == 2
            self.rows = [('id',)]
            observed('keys')
        else:
            match = re.fullmatch(r'SELECT (?:TOP \(\d+\) )?(.+?) FROM (?:"[^"]+"|`[^`]+`|\[[^\]]+\])\.(?:"[^"]+"|`[^`]+`|\[[^\]]+\])(?: LIMIT \d+| FETCH FIRST \d+ ROWS ONLY)?', query)
            assert match, 'Unexpected matrix query; only bounded reviewed selects are supported'
            columns = [part.strip().strip('"`[]') for part in match[1].split(',')]
            assert columns and set(columns) <= {'id', 'label', 'unused'}
            self.rows = [tuple({'id': row[0], 'label': row[1], 'unused': 'MATRIX_UNSELECTED_PRIVATE'}[column] for column in columns) for row in state()['rows']]
            observed('records')
        return self

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchmany(self, size):
        result = self.rows[self.position:self.position + size]
        self.position += len(result)
        return result


def connect(*args, **kwargs):
    if SOURCE == 'sql-server':
        assert args and 'db.example.invalid' in args[0] and 'matrix-sql-server-synthetic-secret' in args[0]
    else:
        assert kwargs.get('password') == 'matrix-' + SOURCE + '-synthetic-secret'
        assert kwargs.get('host', 'db.example.invalid') == 'db.example.invalid'
    observed('connect')
    return Database()


if SOURCE in DATABASES:
    name = {'postgresql': 'pg8000', 'mysql': 'pymysql', 'oracle': 'oracledb', 'sql-server': 'mssql_python'}[SOURCE]
    driver = types.ModuleType(name)
    driver.connect = connect
    if SOURCE == 'oracle':
        driver.defaults = types.SimpleNamespace(fetch_decimals=False)
    elif SOURCE == 'postgresql':
        driver.__path__ = []
        driver.dbapi = types.ModuleType('pg8000.dbapi')
        driver.dbapi.connect = connect
        sys.modules['pg8000.dbapi'] = driver.dbapi
    sys.modules[name] = driver


class SftpLoader(importlib.abc.Loader):
    def __init__(self, delegate):
        self.delegate = delegate

    def create_module(self, spec):
        return self.delegate.create_module(spec)

    def exec_module(self, module):
        self.delegate.exec_module(module)

        class OpenSsh:
            def __init__(self, settings):
                module.settings_for(settings)
                assert settings['host'] == 'sftp.example.invalid'
                assert settings['private_key'].startswith('-----BEGIN OPENSSH ' + 'PRIVATE KEY-----\nSyntheticFixtureOnly')

            def run(self, commands, output_limit=None, timeout=None):
                if commands == ['pwd']:
                    observed('test')
                    return '/synthetic\n'
                assert commands == ['cd "retail"', 'ls -lan']
                observed('inventory')
                result = ''.join('-rw-r--r-- 1 1001 1001 ' + str(len(content.encode())) + ' Jan 01 2026 ' + key.removeprefix('retail/') + '\n' for key, content in state()['contents'].items())
                assert output_limit is not None and len(result.encode()) <= output_limit
                return result

            def list(self, path):
                module.table_path(path)
                files = state()['contents']
                observed('list')
                if path in files:
                    return [(path.rsplit('/', 1)[-1], len(files[path].encode()), False)]
                assert path == 'retail'
                return [(key.removeprefix('retail/'), len(content.encode()), False) for key, content in files.items()]

            def get(self, remote, local):
                module.table_path(remote)
                content = state()['contents'][remote]
                Path(local).write_text(content)
                observed('download')

        module.OpenSsh = OpenSsh


class SftpFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname != 'sftp_reader':
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        assert spec and spec.loader, 'Installed SFTP reader required'
        spec.loader = SftpLoader(spec.loader)
        return spec


if SOURCE == 'sftp':
    sys.meta_path.insert(0, SftpFinder())
