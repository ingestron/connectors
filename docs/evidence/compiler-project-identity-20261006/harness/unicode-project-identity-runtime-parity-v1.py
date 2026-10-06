from pathlib import Path
import json,hashlib,tarfile,sys,zipfile
b=Path(sys.argv[1]).resolve(); p=b/'artifacts/review-readiness-host-v2/inputs.json'; i=json.loads(p.read_text()); results=[]
sha=lambda value: hashlib.sha256(value).hexdigest()
for item in i['archives']:
 owner=b.parent/item['owner']; installed=Path(i[item['owner']]); records=[]; exceptions=[]
 assert sha(Path(item['archive']).read_bytes())==item['archiveSha256']
 with tarfile.open(item['archive']) as archive:
  for member in archive.getmembers():
   if member.isdir():continue
   assert member.isfile(), member.name
   name=member.name.removeprefix('package/'); assert not name.startswith('/') and '..' not in Path(name).parts
   data=archive.extractfile(member).read(); assert (installed/name).read_bytes()==data,name
   owned=(owner/name).read_bytes()
   if owned!=data:
    assert name=='package.json',name
    packed=json.loads(data); source=json.loads(owned)
    source.pop('packageManager',None)
    for key in ['prepack','prepublishOnly']:source.get('scripts',{}).pop(key,None)
    assert packed==source,name
    exceptions.append({'file':name,'normalPackagingRemovedFields':['packageManager','scripts.prepack','scripts.prepublishOnly']})
   records.append({'file':name,'sha256':sha(data),'archiveInstalledByteEqual':True,'ownerFilesEqual':True})
 result={**item,'freshParityRequired':False,'filesCompared':len(records),'metadataExceptions':exceptions,'files':records};results.append(result)
 i['archives'][i['archives'].index(item)]={k:v for k,v in result.items() if k!='files'}
assets=[]
vsix=b.parent/'vscode/build/ingestron-0.15.0.vsix'
with zipfile.ZipFile(vsix) as z:
 for name,digest in i['sha256'].items():
  data=(b/'artifacts/review-readiness-host-v2'/name).read_bytes();assert sha(data)==digest
  leaf=Path(name).name
  assert (b.parent/'ingestron-studio/build/studio'/leaf).read_bytes()==data,name
  assert (b.parent/'vscode/media/studio'/leaf).read_bytes()==data,name
  assert z.read('extension/media/studio/'+leaf)==data,name
  assets.append({'file':name,'sha256':digest,'studioFrozenEditorVsixByteEqual':True})

(b/'outputs/unicode-project-identity-runtime-parity-v1.json').write_text(json.dumps({'result':'passed','archives':results,'sharedAssets':assets,'vsixEntries':len(zipfile.ZipFile(vsix).namelist())},indent=2)+'\n')
print(json.dumps({'result':'passed','archiveFiles':[len(r['files']) for r in results],'sharedAssets':len(assets)}))
