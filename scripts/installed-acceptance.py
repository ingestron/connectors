"""Real installed CLI/core/provider/source, with loopback-only synthetic GitHub."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'test'))
from github_fixture import github_fixture

PROJECT = ROOT / 'build/installed-acceptance'
shutil.rmtree(PROJECT, ignore_errors=True)
PROJECT.mkdir(parents=True)
CLI = Path(os.environ.get('INGESTRON_TEST_CLI', str(ROOT / 'node_modules/ingestron/build/cli/cli/index.js'))).resolve()
SOURCE_VERSION = yaml.safe_load((ROOT / 'connectors/github/connector.yaml').read_text())['version']
SOURCE = f'ingestron/connectors/connectors/github/connector.yaml@{SOURCE_VERSION}'
def installed_package(path, name):
    for parent in path.parents:
        manifest = parent / 'package.json'
        if manifest.is_file():
            value = json.loads(manifest.read_text())
            if value.get('name') == name:
                return value
    raise AssertionError(f'Cannot find installed package {name}')

cli_package = installed_package(CLI, 'ingestron')
core_entry = Path(subprocess.check_output(['node', '--conditions=import', '-e', "console.log(require('node:module').createRequire(process.argv[1]).resolve('@ingestron/core'))", str(CLI)], text=True).strip())
core_package = installed_package(core_entry, '@ingestron/core')
assert subprocess.check_output(['node', str(CLI), '--version'], text=True).strip() == cli_package['version']
assert core_package['version'] == cli_package['dependencies']['@ingestron/core'], 'CLI must use its exact declared core version'
if 'INGESTRON_TEST_CLI' not in os.environ:
    assert cli_package['version'] == json.loads((ROOT / 'package.json').read_text())['devDependencies']['ingestron'], 'Install the pinned registry CLI'



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
    subprocess.run(['git','-C',str(origin),'tag',f'github-{SOURCE_VERSION}'],check=True)
    shutil.copyfile(ROOT / 'examples/github/project.yaml', PROJECT / 'project.yaml')
    project = yaml.safe_load((PROJECT / 'project.yaml').read_text())
    project['providers']['packages']['github'] = SOURCE
    (PROJECT / 'project.yaml').write_text(yaml.safe_dump(project, sort_keys=False))
    call('plugin','install','ingestron/provider-local@0.4.1','--cache-only', *(['--from-git',os.environ['INGESTRON_TEST_PROVIDER']] if os.environ.get('INGESTRON_TEST_PROVIDER') else []))
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
    repository=yaml.safe_load((PROJECT/'project.yaml').read_text())['connections']['github']['settings']['repositories'][0]
    scenario={"mode":"normal"}
    with github_fixture(site, scenario=scenario, repository=repository) as requests:
        subprocess.run([str(python),'-c',"import socket; assert socket.socket.connect.__module__ == 'ingestron_synthetic_transport'"],check=True)
        call('run','--action','discover')
        call('run','--action','review')
        call('run','--run-id','unapproved',ok=False)
        call('run','--action','approve')
        run=call('run','--run-id','issues-001')
        assert run['result']['result']['flows'][0]['tables'][0]['rows']==2
        files=list((PROJECT/'build/generated/data').rglob('issues.parquet'))
        assert len(files)==1
        rows=json.loads(subprocess.check_output([str(python),'-c','import sys,json,pyarrow.parquet as p;print(json.dumps(p.read_table(sys.argv[1]).to_pylist()))',str(files[0])],text=True))
        assert rows==[{'id':1,'title':'Issue 1'},{'id':2,'title':'Issue 2'}],rows
        request_count=len(requests)
        retry=call('run','--retry','issues-001')
        assert retry['result']['attempt']==2
        assert len(requests)==request_count
        assert call('run','status','issues-001')['result']['status']=='succeeded'
        scenario['mode']='empty'
        empty=call('run','--run-id','empty-001')
        assert empty['result']['result']['flows'][0]['tables'][0]['rows']==0
        for failure in ['missing','forbidden','rate','interrupted']:
            scenario['mode']=failure
            failed=call('run','--run-id','failure-'+failure,ok=False)
            assert not list((PROJECT/'build/generated/data').rglob('failure-'+failure+'/commit.json'))
            assert 'synthetic' not in json.dumps(failed), 'Upstream response text must stay private'
        scenario['mode']='normal'
        recovered=call('run','--retry','failure-interrupted')
        assert recovered['result']['status']=='succeeded'
        output=files[0].read_bytes()
        files[0].write_bytes(b'changed')
        call('run','--retry','issues-001',ok=False)
        files[0].write_bytes(output)
        with (PROJECT/'project.yaml').open('a') as file: file.write('\n# stale\n')
        call('run','--retry','issues-001',ok=False)
    evidence={'passed':True,'cli':cli_package['version'],'core':core_package['version'],'node':subprocess.check_output(['node','--version'],text=True).strip(),'provider':'0.4.1','source':'1.33.0','authentication':'anonymous','transport':'loopback synthetic HTTP','rows':rows,'pagination':True,'unapprovedRejected':True,'sourceFreeRetry':True,'tamperRejected':True,'staleRejected':True,'emptySnapshot':True,'httpFailuresRejected':True,'partialFailureRecovered':True,'liveGitHub':False}
    (PROJECT/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print('Installed GitHub connector: pagination, reviewed Parquet, source-free retry, tamper/stale rejection passed')
