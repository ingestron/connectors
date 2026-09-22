"""Prepare a local project with explicit input paths; never replace an existing project."""
from pathlib import Path
import argparse
import hashlib
import json
import base64
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--format', choices=['csv','tsv','json','jsonl','parquet'], default='csv')
a=p.parse_args()
root=Path(__file__).resolve().parent
provenance=json.loads((root/'provenance.json').read_text())
for name,digest in provenance['files'].items():
 path=root/'data'/name
 encoded=path.with_suffix(path.suffix+'.base64')
 if not path.exists() and encoded.exists():
  decoded=base64.b64decode(encoded.read_text())
  if hashlib.sha256(decoded).hexdigest()!=digest:raise SystemExit('Encoded fixture hash differs')
  with path.open('xb') as output:output.write(decoded)
 if hashlib.sha256((root/'data'/name).read_bytes()).hexdigest()!=digest:raise SystemExit('Fixture changed: use a fresh download before setup.')
text=(root/'project.template.yaml').read_text().replace('__FORMAT__',a.format)
for name in ['customers','products','orders']:
 text=text.replace('__'+name.upper()+'_PATH__',json.dumps(str(root/'data'/a.format/(name+'.'+a.format))))
with (root/'project.yaml').open('x') as output:output.write(text)
print('Created project.yaml for '+a.format+'. Review its input paths and three contracts before building.')
