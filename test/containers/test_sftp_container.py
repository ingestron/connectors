"""SFTP connector with the system OpenSSH client against a real SFTP server container.

Opt in with INGESTRON_TEST_CONTAINERS=1 (Docker and OpenSSH required). A fresh
ed25519 key is authorised for the test user and the server's host key is pinned
from ssh-keyscan; synthetic data only.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1] / 'conformance'))
from harness import Conformance, singer_runtime  # noqa: E402

_before = (singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review)
import sftp_runtime  # noqa: E402
import sftp_reader  # noqa: E402
singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review = _before

ENABLED = os.environ.get('INGESTRON_TEST_CONTAINERS') == '1'


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs).stdout.strip()


@unittest.skipUnless(ENABLED, 'Set INGESTRON_TEST_CONTAINERS=1 to run container test beds')
class SftpServerConformance(Conformance, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        base = Path(cls.folder.name)
        run('ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(base / 'id'))
        cls.data = base / 'upload'
        cls.data.mkdir()
        os.chmod(cls.data, 0o777)
        cls.container = run('docker', 'run', '-d', '--rm', '-p', '127.0.0.1::22',
                            '-v', f'{base / "id.pub"}:/home/reader/.ssh/keys/id.pub:ro',
                            '-v', f'{cls.data}:/home/reader/upload', 'atmoz/sftp:latest', 'reader::1001')
        cls.port = int(run('docker', 'port', cls.container, '22').split(':')[-1])
        deadline = time.time() + 90
        while True:
            try:
                lines = [l for l in run('ssh-keyscan', '-p', str(cls.port), '-t', 'ed25519', '127.0.0.1').splitlines()
                         if l and not l.startswith('#')]
                if lines:
                    line = lines[0]
                    break
            except subprocess.CalledProcessError:
                pass
            if time.time() > deadline:
                run('docker', 'rm', '-f', cls.container)
                raise RuntimeError('SFTP server did not start')
            time.sleep(1)
        cls.host_key = ' '.join(line.split()[1:3])
        cls.private_key = (base / 'id').read_text()

    @classmethod
    def tearDownClass(cls):
        subprocess.run(['docker', 'rm', '-f', cls.container], capture_output=True)
        cls.folder.cleanup()

    def make_connector(self):
        for child in self.data.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        return sftp_runtime.Sftp()

    def settings(self):
        return {'host': '127.0.0.1', 'port': self.port, 'user': 'reader', 'private_key': self.private_key,
                'host_key': self.host_key}

    def tables(self):
        return {'customers': {'source': {'path': 'upload/customers.csv', 'format': 'csv'},
                              'columns': [{'name': 'id', 'type': 'BIGINT'}, {'name': 'name', 'type': 'STRING'}]},
                'orders': {'source': {'path': 'upload/orders', 'format': 'csv'},
                           'columns': [{'name': 'amount', 'type': 'DECIMAL(10,2)'}]}}

    def rows(self, stream):
        return [{'id': 1, 'name': 'Ada'}, {'id': 2, 'name': 'Grace'}] if stream == 'customers' \
            else [{'amount': '12.50'}, {'amount': '3.00'}]

    def load(self, stream, rows):
        if stream == 'customers':
            (self.data / 'customers.csv').write_text('id,name\n' + ''.join(f"{r['id']},{r['name']}\n" for r in rows))
            return
        folder = self.data / 'orders'
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir()
        for i, row in enumerate(rows or [None]):
            (folder / f'part-{i}.csv').write_text('amount\n' + (f"{row['amount']}\n" if row else ''))

    def change_schema(self, stream):
        (self.data / 'customers.csv').write_text('id,name,extra\n1,Ada,x\n')

    def break_source(self, stream):
        shutil.rmtree(self.data / 'orders')

    def secret_values(self):
        return [self.private_key.splitlines()[1]]

    def test_wrong_host_key_and_wrong_key_are_rejected(self):
        table = {'path': 'upload/customers.csv', 'format': 'csv', 'types': {}}
        (self.data / 'customers.csv').write_text('id\n1\n')
        wrong_host = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl'
        with self.assertRaises(sftp_reader.SftpError) as error:
            sftp_reader.scan({**self.settings(), 'host_key': wrong_host}, table)
        self.assertEqual(error.exception.code, 'SFTP_HOST_KEY')
        other = Path(self.folder.name) / 'other'
        run('ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(other))
        with self.assertRaises(sftp_reader.SftpError) as error:
            sftp_reader.scan({**self.settings(), 'private_key': other.read_text()}, table)
        self.assertEqual(error.exception.code, 'SFTP_AUTH')


if __name__ == '__main__':
    unittest.main()
