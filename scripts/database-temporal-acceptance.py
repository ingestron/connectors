"""Installed temporal discovery and ingestion on a disposable loopback PostgreSQL."""
import argparse,json,subprocess,sys
from pathlib import Path
from tempfile import TemporaryDirectory
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'test/containers'))
sys.path.insert(0,str(ROOT/'runtime'))
from test_database_conformance import Engine,PASSWORD
IMAGE='postgres:17-alpine@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('cli','sample-harness','provider','python','out','proof','core-archive','cli-archive'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--node',default='node');args=parser.parse_args()
    base=Path(args.out).resolve();base.mkdir(parents=True,exist_ok=True)
    engine=None
    try:
        engine=Engine(IMAGE,5432,{'POSTGRES_PASSWORD':PASSWORD},'postgresql',{'database':'postgres','user':'postgres'})
        engine.run('CREATE TABLE public.orders (id INTEGER PRIMARY KEY, label VARCHAR(100) NOT NULL, day DATE NOT NULL, event TIMESTAMP(6), zoned TIMESTAMPTZ(6), payload JSONB)',
                   "INSERT INTO public.orders VALUES (1,'business-preview-only','2024-02-29','2024-02-29T01:02:03.123456','2024-02-29T01:02:03.123456+00:00','{}'),(2,'second','2024-03-01',NULL,NULL,'{}'),(3,'third','2024-02-29','2024-02-29T23:59:59',NULL,'{}')")
        db=engine.connect()
        try:
            cursor=db.cursor();cursor.execute('SHOW server_version');version=str(cursor.fetchone()[0])
        finally:db.close()
        image_id=subprocess.check_output(['docker','inspect','--format','{{.Image}}',engine.id],text=True,timeout=30).strip()
        with TemporaryDirectory(prefix='temporal-pg-',dir=base) as temporary:
            fixture=Path(temporary)/'fixture.json'
            fixture.write_text(json.dumps({'settings':{'connection':{**engine.settings['connection'],'password':{'$secret':{'env':'SAMPLE_DB_PASSWORD'}}}},'source':{'schema':'public','table':'orders'},'secrets':'SAMPLE_DB_PASSWORD='+PASSWORD+'\n'}));fixture.chmod(0o600)
            def run(command,label):
                child=subprocess.run(command,text=True,capture_output=True,timeout=1200)
                if child.returncode:
                    (base/(label+'-failure.log')).write_text((child.stdout+child.stderr).replace(PASSWORD,'[redacted]'))
                    raise RuntimeError('Installed temporal workflow failed: '+label)
                return json.loads(child.stdout)
            baseline=run([args.node,str(Path(args.sample_harness).resolve()),'--cli',str(Path(args.cli).resolve()),'--connectors',str(ROOT),'--provider',str(Path(args.provider).resolve()),'--connector','postgresql','--fixture',str(fixture),'--python',args.python,'--out',str(base)],'baseline')
            seed=base/'sample-baseline.json';seed.write_text(json.dumps(baseline,indent=2)+'\n')
            command=[args.node,str(ROOT/'scripts/database-temporal-acceptance.mjs'),'--fixture',str(seed),'--python',args.python,'--core-archive',str(Path(args.core_archive).resolve()),'--cli-archive',str(Path(args.cli_archive).resolve()),'--proof',str(Path(args.proof).resolve())]
            run(command+['--phase','initial'],'temporal-initial')
            engine.run("UPDATE public.orders SET day='2024-03-02' WHERE id=2")
            run(command+['--phase','quality-failure'],'temporal-quality')
            engine.run("UPDATE public.orders SET day='2024-03-01' WHERE id=2")
            run(command+['--phase','recovery'],'temporal-recovery')
        proof=Path(args.proof);evidence=json.loads(proof.read_text());evidence.update(databaseVersion=version,image=IMAGE,imageId=image_id,binding='disposable synthetic loopback only',baselineChecks=baseline['checks'])
        proof.write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'result':'passed','proof':str(proof),'checks':len(evidence['checks'])}))
    finally:
        if engine is not None:engine.stop()

if __name__=='__main__':
    try:main()
    except Exception as error:
        print('Synthetic database temporal acceptance failed: '+type(error).__name__,file=sys.stderr);sys.exit(1)
