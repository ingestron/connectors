"""Portable database connectors against real engines in local containers.

Opt in with INGESTRON_TEST_CONTAINERS=1 (Docker required). Each engine runs on a
random localhost port with synthetic data only; the shared conformance suite
then drives the connector through the kit with the real driver. Passing here is
the evidence for `verified` maturity on these connectors.
"""
import os
import subprocess
import sys
import time
import unittest
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1] / 'conformance'))
from harness import Conformance, singer_runtime  # noqa: E402

_before = (singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review)
import database_runtime  # noqa: E402
singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review = _before

ENABLED = os.environ.get('INGESTRON_TEST_CONTAINERS') == '1'
PASSWORD = 'Synthetic-Pass-2026'


def docker(*args):
    return subprocess.run(['docker', *args], check=True, capture_output=True, text=True).stdout.strip()


class Engine:
    """One disposable database container."""

    def __init__(self, image, port, env, dialect, settings, ready_timeout=240):
        self.dialect = dialect
        self.id = docker('run', '-d', '--rm', '-p', f'127.0.0.1::{port}',
                         *[f'-e{k}={v}' for k, v in env.items()], image)
        self.port = int(docker('port', self.id, str(port)).split(':')[-1])
        self.settings = {'connection': {**settings, 'host': '127.0.0.1', 'port': self.port,
                                        'password': PASSWORD, 'tls': 'disable'}}
        deadline = time.time() + ready_timeout
        while True:
            try:
                db = self.connect()
                db.close()
                break
            except Exception:
                if time.time() > deadline:
                    self.stop()
                    raise
                time.sleep(2)

    def connect(self):
        from dbapi_reader import DIALECTS
        return DIALECTS[self.dialect]['connect'](self.settings['connection'])

    def run(self, *statements):
        db = self.connect()
        try:
            cursor = db.cursor()
            for statement in statements:
                cursor.execute(statement)
            db.commit()
        finally:
            db.close()

    def stop(self):
        subprocess.run(['docker', 'rm', '-f', self.id], capture_output=True)


class DatabaseConformance(Conformance):
    """Shared fixture; subclasses give the engine and SQL for their dialect."""
    engine = None
    schema = None
    q = staticmethod(lambda n: '"' + n + '"')
    types = {'id': 'INTEGER', 'name': 'VARCHAR(50)', 'amount': 'DECIMAL(10,2)'}
    drift = None

    @classmethod
    def tearDownClass(cls):
        if cls.engine:
            cls.engine.stop()

    def make_connector(self):
        for table, columns in {'customers': ['id', 'name'], 'orders': ['amount']}.items():
            self.drop(table)
            cols = ', '.join(f'{self.q(c)} {self.types[c]}' for c in columns)
            self.engine.run(f'CREATE TABLE {self.q(self.schema)}.{self.q(table)} ({cols})')
        return database_runtime.Database(self.engine.dialect)

    def drop(self, table):
        try:
            self.engine.run(f'DROP TABLE {self.q(self.schema)}.{self.q(table)}')
        except Exception:
            pass

    def settings(self):
        return self.engine.settings

    def tables(self):
        return {'customers': {'source': {'schema': self.schema, 'table': 'customers'},
                              'columns': [{'name': 'id', 'type': 'BIGINT'},
                                          {'name': 'name', 'type': 'STRING'}]},
                'orders': {'source': {'schema': self.schema, 'table': 'orders'},
                           'columns': [{'name': 'amount', 'type': 'DECIMAL(10,2)'}]}}

    def rows(self, stream):
        return [(1, 'Ada'), (2, 'Grace')] if stream == 'customers' else [(Decimal('12.50'),)]

    def load(self, stream, rows):
        target = f'{self.q(self.schema)}.{self.q(stream)}'
        statements = [f'DELETE FROM {target}']
        for row in rows:
            values = ', '.join(f"'{v}'" if isinstance(v, str) else str(v) for v in row)
            statements.append(f'INSERT INTO {target} VALUES ({values})')
        self.engine.run(*statements)

    def change_schema(self, stream):
        self.engine.run(*self.drift(f'{self.q(self.schema)}.{self.q(stream)}',
                                    self.q('id' if stream == 'customers' else 'amount')))

    def break_source(self, stream):
        self.drop(stream)

    def secret_values(self):
        return [PASSWORD, 'Grace']

    def test_values_survive_with_exact_types(self):
        source = self.connector.source_config(self.config())
        lines = self.read(source, self.discover(source))
        records = {l['stream']: [] for l in lines if l['type'] == 'RECORD'}
        for l in lines:
            if l['type'] == 'RECORD':
                records[l['stream']].append(l['record'])
        self.assertEqual(records['customers'], [{'id': 1, 'name': 'Ada'}, {'id': 2, 'name': 'Grace'}])
        self.assertEqual(records['orders'], [{'amount': Decimal('12.50')}])


@unittest.skipUnless(ENABLED, 'set INGESTRON_TEST_CONTAINERS=1 to run against Docker')
class PostgresConformance(DatabaseConformance, unittest.TestCase):
    schema = 'public'
    drift = staticmethod(lambda t, c: [f'ALTER TABLE {t} ALTER COLUMN {c} TYPE TEXT'])

    @classmethod
    def setUpClass(cls):
        cls.engine = Engine('postgres:17-alpine', 5432, {'POSTGRES_PASSWORD': PASSWORD},
                            'postgresql', {'database': 'postgres', 'user': 'postgres'})


@unittest.skipUnless(ENABLED, 'set INGESTRON_TEST_CONTAINERS=1 to run against Docker')
class MySqlConformance(DatabaseConformance, unittest.TestCase):
    schema = 'retail'
    q = staticmethod(lambda n: '`' + n + '`')
    drift = staticmethod(lambda t, c: [f'ALTER TABLE {t} MODIFY {c} VARCHAR(20)'])

    @classmethod
    def setUpClass(cls):
        cls.engine = Engine('mysql:8.4', 3306, {'MYSQL_ROOT_PASSWORD': PASSWORD, 'MYSQL_DATABASE': 'retail'},
                            'mysql', {'database': 'retail', 'user': 'root'})


@unittest.skipUnless(ENABLED, 'set INGESTRON_TEST_CONTAINERS=1 to run against Docker')
class OracleConformance(DatabaseConformance, unittest.TestCase):
    schema = 'INGESTRON'
    types = {'id': 'NUMBER(10)', 'name': 'VARCHAR2(50)', 'amount': 'NUMBER(10,2)'}
    drift = staticmethod(lambda t, c: [f'ALTER TABLE {t} DROP COLUMN {c}',
                                       f'ALTER TABLE {t} ADD {c} VARCHAR2(20)'])

    @classmethod
    def setUpClass(cls):
        cls.engine = Engine('gvenzl/oracle-free:23-slim-faststart', 1521,
                            {'ORACLE_PASSWORD': PASSWORD, 'APP_USER': 'ingestron',
                             'APP_USER_PASSWORD': PASSWORD},
                            'oracle', {'service': 'FREEPDB1', 'user': 'ingestron'}, 420)


if __name__ == '__main__':
    unittest.main()
