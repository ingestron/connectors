from pathlib import Path
import hashlib,json,sys
b=Path(sys.argv[1]).resolve();inputs=json.loads((b/'outputs/estate-documents-frozen-inputs-v1.json').read_text());assert inputs['status']=='passed'
sys.path.insert(0,inputs['runtime'])
import singer_runtime as entry
workflow=entry.workflow
root=Path(inputs['root']);project=json.loads((root/'project-index.json').read_text());before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
tables=workflow.project_tables(project,root);selection=workflow.project_selection(project,root);contracts=workflow.project_contracts(project,root)
assert len(tables)==len(selection)==len(contracts)==100
assert sum(len(s['fields']) for s in selection.values())==20000
for name,table in tables.items():
 assert table['contract']==contracts[name]
 assert len(table['contract']['schema'][0]['properties'])==len(table['columns'])==200
 assert contracts[name]['id']==name
 assert selection[name]['fields']['column_199']['target']=='business_199'
 assert 'Māori' in contracts[name]['schema'][0]['properties'][0]['description']
source=entry.source_config({'sourceSettings':{},'projectLock':project},folder=root)
assert len(source['objects'])==100 and sum(len(o['types']) for o in source['objects'].values())==20000
config=json.loads((root/'connector.json').read_text())
identity=workflow.runtime_identity(config,root)
assert identity['projectSpecSha256']==config['projectLock']['specificationSha256']
path=root/project['tableDocuments']['documents']['table_099']['path']
original=path.read_bytes()
try:
 path.write_bytes(original.replace(b'business_199',b'changed__199'))
 try:workflow.runtime_identity(config,root)
 except ValueError:pass
 else:raise AssertionError('Changed indexed table was accepted by actual frozen identity checks')
finally:path.write_bytes(original)
# Constructing the source selection must not open rows or publish review/output.
assert before=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
assert not list(root.rglob('*.parquet')) and not (root/'review.json').exists()
records={'status':'passed','scope':'Frozen generated Files1.5.12 runtime map, source-layer indexed project/selection/contracts/actual reader configuration and identity with real pinned dependency inventory; manually constructed source lock uses frozen Core53 canonical hash helper, NOT core/provider preparation, discovery, approval, extraction or run','tables':100,'fields':20000,'distinctContractIds':100,'unicodePreserved':True,'sourceParserTypes':20000,'totalDocumentBytes':inputs['totalDocumentBytes'],'indexBytes':inputs['indexBytes'],'sourceRuntimeIdentity':identity,'changedTableRefused':True,'filesUnchanged':True,'pipelineComplete':False,'installedCliProviderQualification':False}
(b/'outputs/estate-documents-frozen-boundary-v1.json').write_text(json.dumps(records,indent=2)+'\n');print(json.dumps(records))
