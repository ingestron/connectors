"""Object store signing and endpoint rules (PB-064 phase 7)."""
import datetime
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
import object_store_reader as reader


class Signing(unittest.TestCase):
    def test_matches_the_aws_documented_list_objects_example(self):
        # docs.aws.amazon.com/AmazonS3/latest/API/sig-v4-header-based-auth.html, GET Bucket example.
        headers = reader._sign({'access_key_id': 'AKIA' + 'IOSFODNN7EXAMPLE',
                                'secret_access_key': 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'},
                               'us-east-1', 'GET', 'examplebucket.s3.amazonaws.com', '/', 'max-keys=2&prefix=J',
                               datetime.datetime(2013, 5, 24, tzinfo=datetime.timezone.utc))
        self.assertTrue(headers['Authorization'].endswith(
            'Signature=34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7'))

    def test_endpoints(self):
        base = {'bucket': 'retail', 'region': 'ap-southeast-2', 'access_key_id': 'AKIASYNTHETIC',
                'secret_access_key': 'synthetic-secret'}
        self.assertEqual(reader.endpoint(base, 's3'), ('https', 'retail.s3.ap-southeast-2.amazonaws.com', False,
                                                      'ap-southeast-2'))
        self.assertEqual(reader.endpoint(base, 'gcs'), ('https', 'storage.googleapis.com', True, 'auto'))
        self.assertEqual(reader.endpoint({**base, 'endpoint': 'http://127.0.0.1:9000'}, 's3')[:3],
                         ('http', '127.0.0.1:9000', True))
        for bad in [{'endpoint': 'http://storage.example'}, {'bucket': 'Bad_Bucket'}, {'region': 'mars'},
                    {'endpoint': 'https://x.example/path'}]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                reader.endpoint({**base, **bad}, 's3')
        for path in ['/abs', 'a//b', '../x']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                reader.table_path(path)


if __name__ == '__main__':
    unittest.main()
