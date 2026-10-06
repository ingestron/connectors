from pathlib import Path
import json,hashlib,shutil
b=Path('/Users/sacode/sa.projects/intentlabs/repo/ingestron/repo/.studio-finalisation-20261005');d=b.parent/'connectors/docs/evidence/compiler-project-identity-20261006';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for record in json.loads((d/'source-hashes.json').read_text()):assert sha(b.parent/record['owner']/record['path'])==record['afterSha256'],record['path']
for prefix in ['unicode-project-identity-owner-final','unicode-project-identity-root']:
 for p in (b/'outputs').glob(prefix+'*'):
  if p.is_file() and p.suffix in ['.json','.log']:shutil.copyfile(p,d/p.name)
root=b.parent.parent;j=json.loads((root/'docs/solution/product-finalisation-acceptance.json').read_text());paths=[];historical=[]
def walk(v):
 if isinstance(v,dict):
  for k,x in v.items():
   if k=='path' and isinstance(x,str) and x.startswith('/'):
    assert Path(x).exists(),x;paths.append(x)
   walk(x)
 elif isinstance(v,list):
  for x in v:
   if isinstance(x,str) and x.startswith('/'):
    assert Path(x).exists(),x;historical.append(x)
   walk(x)
walk(j);assert not j['complete'] and len(j['workflows'])==16 and all(w['status']=='implementing' for w in j['workflows'])
records=[{'path':str(p.relative_to(d)),'sha256':sha(p)} for p in sorted(d.rglob('*')) if p.is_file() and p.name!='canonical-hashes.json'];(d/'canonical-hashes.json').write_text(json.dumps(records,indent=2)+'\n');assert all(sha(d/r['path'])==r['sha256'] for r in records)
result={'result':'passed','canonicalHashes':len(records),'sourceHashes':len(json.loads((d/'source-hashes.json').read_text())),'absoluteEvidencePathFields':len(paths),'historicalAbsoluteReferences':len(historical),'totalExistingEvidencePaths':len(paths)+len(historical),'complete':False,'implementingWorkflows':16};(b/'outputs/unicode-project-identity-final-evidence-audit-v1.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
