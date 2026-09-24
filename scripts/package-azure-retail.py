"""Extend the immutable retail exercise with Azure project setup."""
from pathlib import Path
import zipfile,hashlib
from legacy_retail_archive import verified_archive
root=Path(__file__).resolve().parents[1]
path=root/'build/release/azure-blob-retail-1.0.0.zip'
with zipfile.ZipFile(verified_archive()) as source,zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as target:
 for name in sorted(source.namelist()+['setup-azure.py']):
  info=zipfile.ZipInfo(name,(2026,9,22,0,0,0));info.external_attr=0o644<<16;info.compress_type=zipfile.ZIP_DEFLATED
  target.writestr(info,(root/'examples/retail-legacy/setup-azure.py').read_bytes() if name=='setup-azure.py' else source.read(name))
print(path);print(hashlib.sha256(path.read_bytes()).hexdigest())
