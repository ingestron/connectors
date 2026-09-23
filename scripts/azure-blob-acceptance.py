"""Qualify the retail download through installed CLI/core and public local provider."""
from pathlib import Path
import os,shutil,subprocess,json,tempfile,hashlib,zipfile,sys,yaml
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"test"))
from azure_blob_fixture import azure_blob_fixture
ROOT=Path(__file__).resolve().parents[1]
CLI=Path(os.environ.get('INGESTRON_TEST_CLI',str(ROOT/'node_modules/ingestron/build/cli/cli/index.js'))).resolve()
WORK=ROOT/'build/azure-blob-acceptance'
os.environ['AZURE_STORAGE_SAS']='sv=2023-11-03&sp=rl&se=2030-01-01&spr=https&sig=synthetic'
if WORK.exists():shutil.rmtree(WORK)
WORK.mkdir(parents=True)
PUBLIC=os.environ.get('INGESTRON_TEST_PUBLIC_SOURCE')=='1'
ARCHIVE=Path(os.environ.get('INGESTRON_TEST_RETAIL_ARCHIVE',str(ROOT/'build/release/azure-blob-retail-1.0.0.zip')))
if not os.environ.get('INGESTRON_TEST_RETAIL_ARCHIVE'):
 subprocess.run(['python3',str(ROOT/'scripts/package-azure-retail.py')],cwd=ROOT,check=True)
records=[]
def command(args,cwd,ok=True):
 p=subprocess.run(args,cwd=cwd,capture_output=True,text=True,timeout=1200)
 records.append({'command':args,'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
 (WORK/'transcript.json').write_text(json.dumps(records,indent=2)+'\n')
 assert (p.returncode==0)==ok,p.stdout+p.stderr
 return p.stdout
def cli(project,*args,ok=True):return command(['node',str(CLI),'--no-input',*args],project,ok)
with tempfile.TemporaryDirectory() as tmp:
 origin=Path(tmp)
 # Install the entire candidate tree: binary/non-package fixtures must not hide packaging failures.
 for name in subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines():
  path=ROOT/name
  if path.is_file():
   target=origin/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
 for args in [['git','init','-q'],['git','add','.'],['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture'],['git','tag','azure-blob-1.0.0']]:command(args,origin)
 for fmt in ['csv','tsv','json','jsonl','parquet']:
  project=WORK/fmt;project.mkdir()
  with zipfile.ZipFile(ARCHIVE) as archive: archive.extractall(project)
  command(['python3','setup-azure.py','--account','sampleaccount','--format',fmt],project)
  cli(project,'plugin','install','ingestron/provider-local@0.4.1')
  cli(project,'plugin','install','ingestron/connectors/connectors/azure-blob/connector.yaml@1.0.0','--tag-prefix','azure-blob-',* ([] if PUBLIC else ['--from-git',str(origin)]))
  cli(project,'check');cli(project,'build');cli(project,'runtime','prepare')
  python=next((project/'.ingestron/runtimes').glob('*/bin/python'))
  site=Path(subprocess.check_output([str(python),'-c','import sysconfig; print(sysconfig.get_paths()["purelib"])'],text=True).strip())
  with azure_blob_fixture(site,project/'data') as transport:
   cli(project,'run','--action','discover');cli(project,'run','--action','review')
   cli(project,'run','--run-id','unapproved',ok=False)
   cli(project,'run','--action','approve');cli(project,'run','--run-id','retail-001')
   command(['python3','inspect-output.py'],project)
   files=list((project/'build/generated/data').rglob('*.parquet'))
   before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
   cli(project,'run','--retry','retail-001')
   assert before=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
   if fmt=='csv':
    path=project/'data/csv/orders.csv';original=path.read_bytes()
    path.write_text(path.read_text().replace('1001','oops'))
    cli(project,'run','--flow','orders_local','--run-id','bad-input',ok=False)
    assert not list((project/'build/generated/data').rglob('bad-input/commit.json'))
    path.write_bytes(original);cli(project,'run','--retry','bad-input')
    path.write_text(path.read_text().replace('order_id','changed_id'))
    cli(project,'run','--flow','orders_local','--run-id','drift',ok=False)
    assert not list((project/'build/generated/data').rglob('drift/commit.json'))
    path.write_bytes(original)
    first=files[0];saved=first.read_bytes();first.write_bytes(b'changed')
    cli(project,'run','--retry','retail-001',ok=False);first.write_bytes(saved)
   for failure in ['denied','changed']:
    transport.mode['value']=failure
    cli(project,'run','--flow','orders_local','--run-id',failure,ok=False)
    assert not list((project/'build/generated/data').rglob(f'{failure}/commit.json'))
    transport.mode['value']='normal';cli(project,'run','--retry',failure)
   assert 'HEAD' in transport.observed and 'GET' in transport.observed
  print(fmt+' installed retail snapshots and retry passed',flush=True)
(WORK/'evidence.json').write_text(json.dumps({'passed':True,'publicSource':PUBLIC,'cli':json.loads((CLI.parents[3]/'package.json').read_text())['version'],'core':json.loads((CLI.parents[3]/'package.json').read_text())['dependencies']['@ingestron/core'],'provider':'0.4.1','azureBlob':'1.0.0','formats':['csv','tsv','json','jsonl','parquet'],'rowsPerSelectedTable':3,'orderValue':'61.95','unapprovedRejected':True,'malformedRejected':True,'schemaDriftRejected':True,'failedRunRecovered':True,'tamperRejected':True,'cloudAccess':False,'transport':'loopback only','conditionalReadRejected':True,'authFailureRecovered':True},indent=2)+'\n')
