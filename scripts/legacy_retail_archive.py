"""Fetch the immutable Files 1.0.1 retail archive for compatibility checks."""
from hashlib import sha256
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'build/release/retail-files-1.0.1-public.zip'
SHA256 = '8c6b4d8b5fa3cc14c28ca7346e34dc83f191dbff8b18e6f2874724a2791d2b9f'
URL = 'https://github.com/ingestron/connectors/releases/download/files-1.0.1/retail-files-1.0.1.zip'


def verified_archive(path=ARCHIVE):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_suffix('.download')
        subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                        '--output', str(temporary), URL], check=True, timeout=120)
        if sha256(temporary.read_bytes()).hexdigest() != SHA256:
            temporary.unlink(missing_ok=True)
            raise ValueError('Published Files 1.0.1 retail archive hash differs')
        temporary.replace(path)
    if sha256(path.read_bytes()).hexdigest() != SHA256:
        raise ValueError('Files 1.0.1 retail archive hash differs')
    return path
