from pathlib import Path
import json,hashlib,sys
b=Path(sys.argv[1]).resolve();old=b/'backups/unicode-project-identity-before-v1/connectors';owner=b.parent/'connectors';results=[]
for folder in sorted((owner/'connectors').iterdir()):
 if not folder.is_dir():continue
 before=json.loads((old/folder.name/'runtime.json').read_text());after=json.loads((folder/'runtime.json').read_text());assert set(before)==set(after)
 changed=[name for name in before if before[name]!=after[name]]
 assert set(changed)<={'singer_bridge.py','singer_runtime.py','snapshot_runtime.py','runtime.lock.json'},(folder.name,changed)
 assert 'singer_bridge.py' in changed and ('snapshot_runtime.py' in changed or 'singer_runtime.py' in changed)
 lock=json.loads(after['runtime.lock.json'])
 for name,digest in lock['files'].items():assert hashlib.sha256(after[name].encode()).hexdigest()==digest,name
 # Existing data/checkpoint codec implementations stay exactly as before.
 first=before['singer_bridge.py'];last=after['singer_bridge.py'];start=first.index('def canonical(');end=first.index('def file_digest(')
 oldcodec=first[start:end];newcodec=last[last.index('def canonical('):last.index('class _CompilerNumber')]
 assert oldcodec==newcodec
 results.append({'id':folder.name,'changedRuntimeFiles':changed,'unchangedUpstreamLocks':True,'unchangedLegacyCodec':True})
assert len(results)==16
(b/'outputs/unicode-project-identity-bundle-audit-v1.json').write_text(json.dumps({'result':'passed','sources':results,'scope':'Generated source-owned bundles: only project hashing/identity and their asset digests change; source readers, requirements, row/checkpoint codec unchanged'},indent=2)+'\n')
print(json.dumps({'result':'passed','sources':len(results)}))
