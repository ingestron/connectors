"""A scaffolded connector passes the conformance suite unchanged (PB-064 phase 3)."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Scaffold(unittest.TestCase):
    def test_new_connector_passes_conformance(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            shutil.copytree(ROOT / 'runtime', work / 'runtime', ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(ROOT / 'test' / 'conformance', work / 'test' / 'conformance',
                            ignore=shutil.ignore_patterns('__pycache__'))
            subprocess.run(['node', str(ROOT / 'scripts' / 'new-connector.mjs'), 'demo-source',
                            '--label', 'Demo source', '--out', str(work)],
                           check=True, capture_output=True, text=True)
            result = subprocess.run(
                [sys.executable, '-m', 'unittest', 'test/runtime/test_conformance_demo_source.py'],
                cwd=work, capture_output=True, text=True,
                env={'PYTHONPATH': str(work / 'runtime'), 'PATH': '/usr/bin:/bin'})
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            self.assertIn('Ran 7 tests', result.stderr)
            again = subprocess.run(['node', str(ROOT / 'scripts' / 'new-connector.mjs'), 'demo-source',
                                    '--out', str(work)], capture_output=True, text=True)
            self.assertNotEqual(again.returncode, 0)
            self.assertIn('Refusing to overwrite', again.stderr)


if __name__ == '__main__':
    unittest.main()
