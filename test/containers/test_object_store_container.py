"""S3 connector against a real S3-compatible server (SeaweedFS) in a local container.

Opt in with INGESTRON_TEST_CONTAINERS=1 (Docker required). The connector signs
every request with SigV4 and SeaweedFS verifies the signatures against its
configured identity, so passing here is
evidence for the S3 request path; synthetic data only.
"""
import datetime
import hashlib
import http.client
import json
import os
import tempfile
import subprocess
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1] / 'conformance'))
from harness import Conformance, singer_runtime  # noqa: E402

_before = (singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review)
import object_store_runtime  # noqa: E402
import object_store_reader as reader  # noqa: E402
singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review = _before

ENABLED = os.environ.get('INGESTRON_TEST_CONTAINERS') == '1'
KEY, SECRET = 'ingestron-test', 'Synthetic-Secret-2026'


def docker(*args):
    return subprocess.run(['docker', *args], check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(ENABLED, 'Set INGESTRON_TEST_CONTAINERS=1 to run container test beds')
class S3ServerConformance(Conformance, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config_dir = tempfile.TemporaryDirectory()
        (Path(cls.config_dir.name) / 's3.json').write_text(json.dumps({'identities': [{
            'name': 'ingestron', 'credentials': [{'accessKey': KEY, 'secretKey': SECRET}],
            'actions': ['Admin', 'Read', 'List', 'Write']}]}))
        cls.container = docker('run', '-d', '--rm', '-p', '127.0.0.1::8333', '-v', f'{cls.config_dir.name}:/config:ro',
                               'chrislusf/seaweedfs:latest', 'server', '-dir=/data', '-s3', '-s3.port=8333',
                               '-s3.config=/config/s3.json')
        cls.port = int(docker('port', cls.container, '8333').split(':')[-1])
        deadline = time.time() + 180
        while True:
            try:
                cls.put('')
                break
            except Exception:
                if time.time() > deadline:
                    docker('rm', '-f', cls.container)
                    raise
                time.sleep(1)

    @classmethod
    def tearDownClass(cls):
        docker('rm', '-f', cls.container)
        cls.config_dir.cleanup()

    @classmethod
    def put(cls, key, data=None, method='PUT'):
        """Create the bucket (key '') or put/delete an object with a signed request."""
        host = f'127.0.0.1:{cls.port}'
        path = '/retail' + ('/' + key if key else '')
        payload = hashlib.sha256(data or b'').hexdigest()
        headers = reader._sign({'access_key_id': KEY, 'secret_access_key': SECRET}, 'us-east-1', method, host,
                               path, '', datetime.datetime.now(datetime.timezone.utc), payload)
        connection = http.client.HTTPConnection(host, timeout=30)
        connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        response.read()
        connection.close()
        if response.status not in (200, 204, 409): raise RuntimeError(f'S3 server {method} {response.status}')

    def make_connector(self):
        for key in list(getattr(self, 'keys', [])):
            self.put(key, method='DELETE')
        self.keys = set()
        return object_store_runtime.ObjectStore('s3')

    def settings(self):
        return {'bucket': 'retail', 'region': 'us-east-1', 'access_key_id': KEY, 'secret_access_key': SECRET,
                'endpoint': f'http://127.0.0.1:{self.port}'}

    def tables(self):
        return {'customers': {'source': {'path': 'v1/customers.csv', 'format': 'csv'},
                              'columns': [{'name': 'id', 'type': 'BIGINT'}, {'name': 'name', 'type': 'STRING'}]},
                'orders': {'source': {'path': 'v1/orders', 'format': 'csv'},
                           'columns': [{'name': 'amount', 'type': 'DECIMAL(10,2)'}]}}

    def rows(self, stream):
        return [{'id': 1, 'name': 'Ada'}, {'id': 2, 'name': 'Grace'}] if stream == 'customers' \
            else [{'amount': '12.50'}, {'amount': '3.00'}]

    def write(self, key, text):
        self.put(key, text.encode())
        self.keys.add(key)

    def load(self, stream, rows):
        if stream == 'customers':
            self.write('v1/customers.csv', 'id,name\n' + ''.join(f"{r['id']},{r['name']}\n" for r in rows))
            return
        for key in [k for k in self.keys if k.startswith('v1/orders/')]:
            self.put(key, method='DELETE')
            self.keys.discard(key)
        for i, row in enumerate(rows or [None]):
            self.write(f'v1/orders/part-{i}.csv', 'amount\n' + (f"{row['amount']}\n" if row else ''))

    def change_schema(self, stream):
        self.write('v1/customers.csv', 'id,name,extra\n1,Ada,x\n')

    def break_source(self, stream):
        for key in [k for k in self.keys if k.startswith('v1/orders/')]:
            self.put(key, method='DELETE')
        self.write('v1/orders/notes.txt', 'not data')

    def secret_values(self):
        return [SECRET]

    def test_wrong_secret_is_rejected_by_the_server(self):
        with self.assertRaises(reader.StoreError) as error:
            reader.scan('S3', {**self.settings(), 'secret_access_key': 'wrong-secret-value'}, 's3',
                        {'path': 'v1/customers.csv', 'format': 'csv', 'types': {}})
        self.assertIn(error.exception.code, ('S3_AUTH', 'S3_FORBIDDEN'))


if __name__ == '__main__':
    unittest.main()
