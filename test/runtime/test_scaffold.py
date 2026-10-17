"""The standalone starter builds and runs without copying sibling source code."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NODE = shutil.which('node')


class Scaffold(unittest.TestCase):
    def scaffold(self, root, *options):
        return subprocess.run([NODE, str(ROOT/'scripts/new-connector.mjs'), 'demo-source', '--out', str(root), *options], capture_output=True, text=True)

    def test_standalone_package_passes_conformance_and_has_locked_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'standalone'
            result = self.scaffold(root, '--label', 'Demo """ source')
            self.assertEqual(result.returncode, 0, result.stderr)
            test = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'test', '-p', 'test_*.py'], cwd=root, capture_output=True, text=True, env={**os.environ, 'PYTHONPATH':str(root/'runtime')})
            self.assertEqual(test.returncode, 0, test.stderr[-4000:])
            self.assertIn('Ran 11 tests', test.stderr)
            manifest=json.loads((root/'connector.yaml').read_text())
            content=(root/manifest['runtime']['path']).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(),manifest['runtime']['sha256'])
            assets=json.loads(content);lock=json.loads(assets['runtime.lock.json'])
            self.assertEqual(set(assets)-{'runtime.lock.json'},set(lock['files']))
            for name, expected in lock['files'].items():self.assertEqual(hashlib.sha256(assets[name].encode()).hexdigest(),expected)
            self.assertEqual(manifest['connector'],'singer:demo-source@23.0.1')
            self.assertEqual(manifest['source']['reference']['maturity'],'preview')
            self.assertEqual(manifest['sourceAccess']['actions'],['test','inventory','metadata','sample'])
            self.assertFalse(any('test/' in name or 'mock' in name for name in assets))
            before={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
            again=self.scaffold(root);self.assertNotEqual(again.returncode,0);self.assertIn('Refusing to overwrite',again.stderr)
            after={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(before,after)
            subprocess.run([NODE,str(root/'scripts/build.mjs')],cwd=tmp,check=True,capture_output=True)
            self.assertEqual((root/'runtime.json').read_bytes(),content)

    def test_collision_and_invalid_options_do_not_partially_write_a_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'existing';root.mkdir();(root/'keep.txt').write_text('preserved')
            self.assertNotEqual(self.scaffold(root).returncode,0)
            self.assertEqual(list(root.iterdir()),[root/'keep.txt']);self.assertEqual((root/'keep.txt').read_text(),'preserved')
            for options in (['--label','bad\nlabel'],['--repository','https://user:secret@example.invalid/source'],['--unknown','value'],['--label','ok','--label','again']):
                target=Path(tmp)/'new';result=self.scaffold(target,*options);self.assertNotEqual(result.returncode,0);self.assertFalse(target.exists())
            self.assertEqual(list(Path(tmp).iterdir()),[root])


if __name__ == '__main__':unittest.main()
