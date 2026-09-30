"""Build the Azure Blob 2.0 retail download: the current retail exercise plus Azure setup."""
from pathlib import Path
import hashlib,subprocess,sys,zipfile
root=Path(__file__).resolve().parents[1]
files=root/'build/release/retail-files-1.2.0.zip'
subprocess.run([sys.executable,str(root/'scripts/package-retail.py')],cwd=root,check=True,capture_output=True)
path=root/'build/release/azure-blob-retail-2.0.0.zip'
with zipfile.ZipFile(files) as source,zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as target:
 for name in sorted(source.namelist()+['setup-azure.py']):
  info=zipfile.ZipInfo(name,(2026,9,30,0,0,0));info.external_attr=0o100644<<16;info.compress_type=zipfile.ZIP_DEFLATED
  target.writestr(info,(root/'examples/retail/setup-azure.py').read_bytes() if name=='setup-azure.py' else source.read(name))
print(path);print(hashlib.sha256(path.read_bytes()).hexdigest())
