"""Extend the immutable retail exercise with Azure project setup."""
from pathlib import Path
import zipfile,subprocess,hashlib
root=Path(__file__).resolve().parents[1]
subprocess.run(['python3',str(root/'scripts/package-retail.py')],cwd=root,check=True)
path=root/'build/release/azure-blob-retail-1.0.0.zip'
with zipfile.ZipFile(root/'build/release/retail-files-1.0.1.zip') as source,zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as target:
 for name in sorted(source.namelist()+['setup-azure.py']):
  info=zipfile.ZipInfo(name,(2026,9,22,0,0,0));info.external_attr=0o644<<16;info.compress_type=zipfile.ZIP_DEFLATED
  target.writestr(info,(root/'examples/retail/setup-azure.py').read_bytes() if name=='setup-azure.py' else source.read(name))
print(path);print(hashlib.sha256(path.read_bytes()).hexdigest())
