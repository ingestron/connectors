"""Redirect installed cloud listing transports to a socket-fenced local fixture."""
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit, quote
from xml.sax.saxutils import escape

OWNER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OWNER / 'test/mocks'))
from loopback import loopback

config = json.loads(Path(sys.argv[1]).read_text())
root = Path(config['root'])
python = next((root / '.ingestron/runtime-cache').glob('*/bin/python'))
site = Path(subprocess.check_output([str(python), '-c', 'import sysconfig; print(sysconfig.get_paths()["purelib"])'], text=True).strip())
keys = ['retail/customers.tsv', 'retail/orders.csv', 'retail/readme.txt', 'retail/sub/products.parquet']
requests = []


def handle(host, method, target, headers, body):
    query = parse_qs(urlsplit(target).query)
    requests.append({'host':host, 'method':method, 'path':urlsplit(target).path,
                     'prefix':query.get('prefix',[''])[0]})
    assert method == 'GET' and body is None
    if host == 'syntheticretail.blob.core.windows.net':
        assert query['comp'] == ['list'] and query['restype'] == ['container']
        assert query['sig'] == ['synthetic-secret'] and headers['x-ms-version'] == '2023-11-03'
        limit = int(query['maxresults'][0]); start = int(query.get('marker',['0'])[0])
    else:
        assert headers['Authorization'].startswith('AWS4-HMAC-SHA256 Credential=SYNTHETIC-KEY/')
        assert query['list-type'] == ['2'] and query['encoding-type'] == ['url']
        limit = int(query['max-keys'][0]); start = int(query.get('continuation-token',['0'])[0])
    prefix = query['prefix'][0]
    if prefix == 'malformed/':
        return 200, b'<Error><Message>PRIVATE_BODY_VALUE synthetic-secret</Message></Error>'
    matching = [key for key in keys if key.startswith(prefix)]
    page = matching[start:start+limit]; more = start+limit < len(matching)
    if host == 'syntheticretail.blob.core.windows.net':
        blobs = ''.join('<Blob><Name>'+escape(key)+'</Name><Properties><Content-Length>12</Content-Length></Properties></Blob>' for key in page)
        data = '<EnumerationResults><Blobs>'+blobs+'</Blobs><NextMarker>'+ (str(start+limit) if more else '')+'</NextMarker></EnumerationResults>'
    else:
        contents = ''.join('<Contents><Key>'+quote(key,safe='/')+'</Key><Size>12</Size></Contents>' for key in page)
        data = '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'+contents+'<EncodingType>url</EncodingType><IsTruncated>'+('true' if more else 'false')+'</IsTruncated>'
        if more: data += '<NextContinuationToken>'+str(start+limit)+'</NextContinuationToken>'
        data += '</ListBucketResult>'
    return 200, data.encode()


with loopback(site, handle, {'syntheticretail.s3.us-east-1.amazonaws.com', 'storage.googleapis.com', 'syntheticretail.blob.core.windows.net'}):
    if config.get('studioScript'):
        studio = Path(config['studioScript']).parents[1]
        command = ['node', '--conditions', 'react-server', '--import', 'tsx', config['studioScript'], '--verify', sys.argv[1]]
        child = subprocess.run(command, cwd=studio, text=True, capture_output=True, timeout=550)
    else:
        child = subprocess.run(['node', config['script'], '--verify', sys.argv[1]], text=True, capture_output=True, timeout=550)
    sys.stdout.write(child.stdout); sys.stderr.write(child.stderr)
assert child.returncode == 0, 'Installed cloud file inventory assertions failed'
assert requests and all(r['method']=='GET' for r in requests)
assert {r['host'] for r in requests} == {'syntheticretail.s3.us-east-1.amazonaws.com', 'storage.googleapis.com', 'syntheticretail.blob.core.windows.net'}
assert all(r['path'] in ('/', '/syntheticretail', '/bronze') for r in requests), 'Unexpected object download'
proof = Path(config['proof']); evidence = json.loads(proof.read_text())
evidence['transportRequests'] = requests
evidence['listingOnlyVerified'] = True
evidence['fixtureHooksRemoved'] = not (site/'ingestron_loopback.pth').exists()
assert evidence['fixtureHooksRemoved']
proof.write_text(json.dumps(evidence,indent=2)+'\n')
