"""SQL Server connector against SQL Server 2022 (Developer) in a local container.

Opt in with INGESTRON_TEST_CONTAINERS=1. The container presents a self-signed
certificate, so this test's connect function trusts it; the shipped reader
always verifies certificates. TLS verification is therefore not covered here.
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
import sql_server_runtime  # noqa: E402
singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review = _before

ENABLED = os.environ.get('INGESTRON_TEST_CONTAINERS') == '1'
PASSWORD = 'Synthetic-Pass-2026'


def trusted_connect(conn_string, timeout=None):
    import mssql_python
    return mssql_python.connect(
        conn_string.replace('TrustServerCertificate=no', 'TrustServerCertificate=yes'), timeout=timeout)


@unittest.skipUnless(ENABLED, 'set INGESTRON_TEST_CONTAINERS=1 to run against Docker')
class SqlServerContainerConformance(Conformance, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run = lambda *a: subprocess.run(['docker', *a], check=True, capture_output=True, text=True).stdout.strip()
        cls.container = run('run', '-d', '--rm', '-p', '127.0.0.1::1433', '-e', 'ACCEPT_EULA=Y',
                            '-e', f'MSSQL_SA_PASSWORD={PASSWORD}', '-e', 'MSSQL_PID=Developer',
                            'mcr.microsoft.com/mssql/server:2022-latest')
        cls.port = int(run('port', cls.container, '1433').split(':')[-1])
        deadline = time.time() + 240
        while True:
            try:
                cls.execute('master', "IF DB_ID('retail') IS NULL CREATE DATABASE retail")
                break
            except Exception:
                if time.time() > deadline:
                    cls.tearDownClass()
                    raise
                time.sleep(3)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(['docker', 'rm', '-f', cls.container], capture_output=True)

    @classmethod
    def connection(cls, database='retail'):
        return {'server': '127.0.0.1', 'port': cls.port, 'database': database,
                'authentication': {'method': 'sql-password', 'username': 'sa', 'password': PASSWORD}}

    @classmethod
    def execute(cls, database, *statements):
        from sql_server_reader import connection_string
        db = trusted_connect(connection_string(cls.connection(database)).replace(
            'ApplicationIntent=ReadOnly', 'ApplicationIntent=ReadWrite'), timeout=10)
        try:
            db.autocommit = True
            cursor = db.cursor()
            for statement in statements:
                cursor.execute(statement)
        finally:
            db.close()

    def make_connector(self):
        for table, columns in {'customers': 'id INT NOT NULL, name NVARCHAR(50)',
                               'orders': 'amount DECIMAL(10,2)'}.items():
            self.execute('retail', f"DROP TABLE IF EXISTS dbo.{table}", f"CREATE TABLE dbo.{table} ({columns})")
        return sql_server_runtime.SqlServer(connect=trusted_connect)

    def settings(self):
        return {'connection': self.connection()}

    def tables(self):
        return {'customers': {'source': {'schema': 'dbo', 'table': 'customers'},
                              'columns': [{'name': 'id', 'type': 'BIGINT'}, {'name': 'name', 'type': 'STRING'}]},
                'orders': {'source': {'schema': 'dbo', 'table': 'orders'},
                           'columns': [{'name': 'amount', 'type': 'DECIMAL(10,2)'}]}}

    def rows(self, stream):
        return [(1, 'Ada'), (2, 'Grace')] if stream == 'customers' else [(Decimal('12.50'),)]

    def load(self, stream, rows):
        values = [', '.join(f"N'{v}'" if isinstance(v, str) else str(v) for v in row) for row in rows]
        self.execute('retail', f'DELETE FROM dbo.{stream}', *[f'INSERT INTO dbo.{stream} VALUES ({v})' for v in values])

    def change_schema(self, stream):
        column = 'id' if stream == 'customers' else 'amount'
        self.execute('retail', f'ALTER TABLE dbo.{stream} ALTER COLUMN {column} NVARCHAR(20)')

    def break_source(self, stream):
        self.execute('retail', f'DROP TABLE dbo.{stream}')

    def secret_values(self):
        return [PASSWORD, 'Grace']


if __name__ == '__main__':
    unittest.main()
