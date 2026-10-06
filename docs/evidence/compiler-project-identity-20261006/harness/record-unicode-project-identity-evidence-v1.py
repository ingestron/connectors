from pathlib import Path
import json,hashlib,shutil,difflib
b=Path('/Users/sacode/sa.projects/intentlabs/repo/ingestron/repo/.studio-finalisation-20261005');d=b.parent/'connectors/docs/evidence/compiler-project-identity-20261006';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def proof(name,key='status'):
 a=json.loads((b/'outputs'/name).read_text());assert a[key]=='passed',name;return a
for name in ['unicode-project-identity-wide-v3.json','unicode-project-identity-wide-qualified-v1.json','unicode-project-identity-wide-report-parity-v3.json','unicode-project-identity-denials-v2.json']:proof(name)
metrics=proof('unicode-project-identity-wide-report-metrics-v3.json','result');assert metrics['reportBytes']==1237346 and metrics['pageCount']==5
assert len(proof('unicode-project-identity-wide-qualified-v1.json')['physical'])==10
for phase,count in [('prepare',48),('host',144),('quality',22)]:
 a=proof('unicode-project-identity-source-'+phase+'-v1.json','result');assert len(a['checks'])==count
source=proof('unicode-project-identity-source-parity-v1.json','result');assert source['packages']==17 and len(source['files'])==773
runtime=proof('unicode-project-identity-runtime-parity-v1.json','result');assert len(runtime['sharedAssets'])==5
assert '# pass 5' in (b/'outputs/unicode-project-identity-connectors-gate-v2.log').read_text();assert 'Ran 291 tests' in (b/'outputs/unicode-project-identity-connectors-gate-v2.log').read_text();assert '\nOK\n' in (b/'outputs/unicode-project-identity-connectors-gate-v2.log').read_text()
for version,stage in [('v1','prepare'),('v2','run')]:
 a=json.loads((b/f'outputs/unicode-project-identity-wide-{version}.json').read_text());assert a['status']=='failed' and a['stage']==stage
assert 'Configuration/catalogue exceeds 2 MB' in json.loads((b/'outputs/unicode-project-identity-wide-failure-probe-v1.json').read_text())['stdout']
assert 'review.json:ValueError:Configuration/catalogue exceeds 2 MB' in json.loads((b/'outputs/unicode-project-identity-review-bound-probe-v1.json').read_text())['stdout']
assert proof('unicode-project-identity-bundle-audit-v1.json','result')['scope']
assert proof('unicode-project-identity-private-versions-v2.json','result')['publicCatalogueUnchanged']
assert proof('unicode-project-identity-static-ui-parity-v1.json','result')['actualOwnerSourceFilesCompared']==52
assert proof('unicode-project-identity-preview-health-v1.json','result')['workspaces']==8
d.mkdir(parents=True,exist_ok=True);provenance=[]
def copy(p,q):
 q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q);provenance.append({'source':str(p),'sourceSha256':sha(p),'copy':str(q.relative_to(d))})
for p in (b/'outputs').glob('unicode-project-identity-*'):
 if p.is_file() and p.suffix in ['.json','.log']:copy(p,d/p.name)
for p in (b/'scripts').glob('*unicode-project-identity*'):
 if p.is_file():copy(p,d/'harness'/(p.name+'.txt' if p.suffix=='.mjs' else p.name))
for p in (b/'artifacts/unicode-project-identity-matrix-harness-v1').iterdir():
 if p.is_file():copy(p,d/'harness'/('matrix-'+p.name+'.txt' if p.suffix=='.mjs' else 'matrix-'+p.name))
copy(b/'artifacts/review-readiness-host-v2/inputs.json',d/'immutable-inputs.json')
copy(b/'artifacts/review-readiness-ui-v1/provenance.json',d/'static-ui-source-provenance.json')
copy(b/'outputs/review-readiness-unicode-digest-comparison-v1.json',d/'original-project-digest-failure.json')
copy(b/'outputs/review-readiness-unicode-wide-v2.json',d/'original-multilingual-pipeline-failure.json')
copy(b/'outputs/review-readiness-unicode-bounded-report-v1.json',d/'report-helper-source-provenance.json')
records=[];patch=[]
for r in json.loads((b/'outputs/unicode-project-identity-before-v1.json').read_text()):
 p=b.parent/r['owner']/r['path'];old=b/'backups/unicode-project-identity-before-v1'/r['path'];assert sha(old)==r['sha256'];records.append({**r,'afterSha256':sha(p)});patch+=list(difflib.unified_diff(old.read_text().splitlines(True),p.read_text().splitlines(True),fromfile='before/'+r['owner']+'/'+r['path'],tofile='after/'+r['owner']+'/'+r['path']))
p=b.parent/'connectors/test/runtime/test_project_identity.py';records.append({'owner':'connectors','path':'test/runtime/test_project_identity.py','sha256':None,'afterSha256':sha(p)});patch+=list(difflib.unified_diff([],p.read_text().splitlines(True),fromfile='/dev/null',tofile='after/connectors/test/runtime/test_project_identity.py'))
(d/'source-hashes.json').write_text(json.dumps(records,indent=2)+'\n');(d/'scoped-change.patch').write_text(''.join(patch));(d/'raw-source-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
acceptance={'apiVersion':'ingestron.compiler-project-identity-acceptance/v1','date':'2026-10-06','status':'passed','candidate':{'cli':'0.17.21','core':'0.12.51','publicPinsChanged':False,'privateSourceVersions':{x['id']:x['version'] for x in json.loads(Path(json.loads((b/'outputs/unicode-project-identity-matrix-input-v1.json').read_text())['configPath']).read_text())['records']}},'scope':{'installedLocalMultilingualMetadata':True,'actualFrozenSharedHost':True,'sdkCliMcpPagedRead':True,'staticActualMappingRows':True,'sixteenSyntheticSources':True,'realVendorAccounts':False,'mountedInteraction':False,'enterpriseComplete':False},'verification':{'connectorsNodeTests':5,'connectorsRuntimeTests':291,'projectIdentityFocusedTests':4,'legacyReceiptCheckpointCodecByteUnchanged':True,'sourceRuntimeBundles':16,'sourcePreparationChecks':48,'sharedHostChecks':144,'businessQualityChecks':22,'lockedPackages':17,'consumedOwnerFiles':773,'coreRuntimeFiles':156,'cliRuntimeFiles':29,'unchangedExactSharedAssets':5,'multilingualTables':10,'columnsPerTable':200,'physicalOutputs':10,'measuredRows':30,'staticMappingRows':2000,'staticPages':80,'previewDisplayedColumns':50,'previewTotalColumns':200,'reviewBytes':metrics['reportBytes'],'reviewPages':metrics['pageCount'],'approvalDigest':metrics['approvalDigest'],'wholeReviewBytesExact':True,'decodedDescriptionsExact':True,'denialGroups':len(proof('unicode-project-identity-denials-v2.json')['checks']),'preservedCommittedOutputFiles':proof('unicode-project-identity-denials-v2.json')['preservedOutputFiles']},'remaining':['Twenty tables with full multilingual field descriptions produce a 2125203-byte configuration and fail the existing two-million-byte runtime input bound before discovery','Twenty tables with shorter multilingual descriptions prepare/review but produce a 2146233-byte review; approval fails the same runtime bound without publication','The earlier hundred-table/two-hundred-column fixture exceeds the existing provider validation transport bound before preparation','Scale limits and their early user-facing diagnostics need a bounded cross-component repair; existing limits were not increased','Full upgraded-checkpoint migration from an older source version was not rerun; this slice preserves the codec bytes and passes current checkpoint/migration regression tests','Mounted, keyboard and narrow-layout usability; broader native/provider, cross-project ownership, recovery/CDC and independent engineer qualification remain open','Original preview still uses its original configured compiler; qualified private packages are isolated here']}
(d/'acceptance.json').write_text(json.dumps(acceptance,indent=2)+'\n');print(d)
