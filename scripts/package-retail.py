"""Build the Files 1.1 retail download from reviewed, hash-pinned fixtures."""
from pathlib import Path
import json,hashlib,zipfile,base64
root=Path(__file__).resolve().parents[1]
source=root/'examples/retail'
manifest=json.loads((source/'provenance.json').read_text())
def data(name):
 p=source/name
 return base64.b64decode(p.with_suffix(p.suffix+'.base64').read_text(),validate=False) if name.endswith('.parquet') else p.read_bytes()
for name,expected in manifest['files'].items():
 assert hashlib.sha256(data('data/'+name)).hexdigest()==expected,name
names=['README.md','LICENSE','.gitignore','provenance.json','expected.json','setup.py','project.template.yaml','inspect-output.py']+['contracts/'+name+'.odcs.yaml' for name in ['customers','products','orders']]+['data/'+n for n in manifest['files']]
target=root/'build/release/retail-files-1.1.0.zip';target.parent.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as out:
 for name in sorted(names):
  info=zipfile.ZipInfo(name,(2026,9,24,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644 << 16
  out.writestr(info,data(name))
print(target)
print(hashlib.sha256(target.read_bytes()).hexdigest())
