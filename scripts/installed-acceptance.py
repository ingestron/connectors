"""Real installed CLI/core/provider/source, with loopback-only synthetic GitHub."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'test'))
from github_fixture import github_fixture

PROJECT = ROOT / 'build/installed-acceptance'
shutil.rmtree(PROJECT, ignore_errors=True)
PROJECT.mkdir(parents=True)
CLI = Path(os.environ.get('INGESTRON_TEST_CLI', str(ROOT / 'node_modules/ingestron/build/cli/cli/index.js'))).resolve()
SOURCE = 'ingestron/connectors/connectors/github/connector.yaml@1.32.1'
assert subprocess.check_output(['node', str(CLI), '--version'], text=True).strip() == '0.12.1', 'Install qualified CLI 0.12.1 (or supply its installed archive via INGESTRON_TEST_CLI)' 


def call(*args, ok=True):
    proc = subprocess.run(['node', str(CLI), '--project', str(PROJECT), '--json', '--no-input', *args], capture_output=True, text=True, timeout=1200)
    try: result = json.loads(proc.stdout)
    except Exception: raise RuntimeError(proc.stderr + proc.stdout) from None
    assert result['ok'] == ok, result
    return result


with tempfile.TemporaryDirectory(prefix='source-origin-') as temp:
    origin = Path(temp)
    shutil.copytree(ROOT / 'connectors/github', origin / 'connectors/github')
    subprocess.run(['git','init','-q',str(origin)],check=True)
    subprocess.run(['git','-C',str(origin),'add','.'],check=True)
    subprocess.run(['git','-C',str(origin),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture'],check=True)
    subprocess.run(['git','-C',str(origin),'tag','github-1.32.1'],check=True)
    shutil.copyfile(ROOT / 'examples/github/project.yaml', PROJECT / 'project.yaml')
    call('plugin','install','ingestron/provider-local@0.4.0','--cache-only')
    options=[] if os.environ.get('INGESTRON_TEST_PUBLIC_SOURCE') == '1' else ['--from-git',str(origin)]
    call('plugin','install',SOURCE,'--tag-prefix','github-','--cache-only',*options)
    call('check')
    call('build')
    call('run','--action','discover',ok=False)
    first=call('runtime','prepare')
    second=call('runtime','prepare')
    assert all(f['reused'] for f in second['result']['result']['flows'])
    python=next((PROJECT/'.ingestron/runtimes').glob('*/bin/python'))
    site=Path(subprocess.check_output([str(python),'-c','import sysconfig; print(sysconfig.get_paths()["purelib"])'],text=True).strip())
    envfile=PROJECT/'.env'
    envfile.write_text('INGESTRON_GITHUB_TOKEN=synthetic-fixture-value\n')
    with github_fixture(site) as requests:
        subprocess.run([str(python),'-c',"import socket; assert socket.socket.connect.__module__ == 'ingestron_synthetic_transport'"],check=True)
        call('run','--action','discover','--secrets-file','.env')
        call('run','--action','review')
        call('run','--run-id','unapproved','--secrets-file','.env',ok=False)
        call('run','--action','approve')
        run=call('run','--run-id','issues-001','--secrets-file','.env')
        assert run['result']['result']['flows'][0]['tables'][0]['rows']==2
        files=list((PROJECT/'build/generated/data').rglob('issues.parquet'))
        assert len(files)==1
        rows=json.loads(subprocess.check_output([str(python),'-c','import sys,json,pyarrow.parquet as p;print(json.dumps(p.read_table(sys.argv[1]).to_pylist()))',str(files[0])],text=True))
        assert rows==[{'id':1,'title':'Issue 1'},{'id':2,'title':'Issue 2'}],rows
        request_count=len(requests)
        envfile.unlink()
        retry=call('run','--retry','issues-001')
        assert retry['result']['attempt']==2
        assert len(requests)==request_count
        assert call('run','status','issues-001')['result']['status']=='succeeded'
        output=files[0].read_bytes()
        files[0].write_bytes(b'changed')
        call('run','--retry','issues-001',ok=False)
        files[0].write_bytes(output)
        with (PROJECT/'project.yaml').open('a') as file: file.write('\n# stale\n')
        call('run','--retry','issues-001',ok=False)
    evidence={'passed':True,'cli':'0.12.1','core':'0.12.0','provider':'0.4.0','source':'1.32.1','transport':'loopback synthetic HTTP','rows':rows,'pagination':True,'unapprovedRejected':True,'sourceFreeRetry':True,'tamperRejected':True,'staleRejected':True,'liveGitHub':False}
    (PROJECT/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print('Installed GitHub connector: pagination, reviewed Parquet, source-free retry, tamper/stale rejection passed')
