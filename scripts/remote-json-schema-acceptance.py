"""Installed remote JSON acceptance: real SFTP and fenced cloud/Graph APIs."""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import parse_qs, unquote, urlsplit
import uuid

OWNER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OWNER / 'test/mocks'))
from graph_api import GraphApi, SITE_ID
from loopback import loopback

config_path = Path(sys.argv[1])
config = json.loads(config_path.read_text())
root = Path(config['root'])
python = next((root / '.ingestron/runtime-cache').glob('*/bin/python'))
site = Path(subprocess.check_output([str(python), '-c', 'import sysconfig; print(sysconfig.get_paths()["purelib"])'], text=True).strip())
fixture = root / 'fixture'
fixture.mkdir(mode=0o700)
upload = fixture / 'upload'
upload.mkdir(mode=0o777)
os.chmod(upload, 0o777)
contents = {
    'customers.tsv': b'id\tlabel\n1\tSynthetic Customer\n',
    'orders.csv': b'id,label\n1,PRIVATE_PREVIEW\n2,Second Order\n3,Third Order\n',
    'products.csv': b'id,label\n1,First Product\n2,Second Product\n',
    'readme.txt': b'Ignored non-data object',
}
json_rows = [
    {'id':9007199254740993,'amount':12.34,'label':'PRIVATE_JSON_RECORD','active':True},
    {'id':2,'amount':0.01,'label':'Second row','active':False},
    {'id':3,'amount':1.1,'label':'Third row','active':True},
]
contents.update({
    'orders.jsonl': b'{"id":9007199254740993,"amount":12.340,"label":"PRIVATE_JSON_RECORD","active":true}\n' +
                     b'{"id":2,"amount":0.01,"label":"Second row","active":false}\n' +
                     b'{"id":3,"amount":1.1,"label":"Third row","active":true}\n',
    'customers.json': json.dumps(json_rows).encode(),
    'bad.jsonl': b'PRIVATE_BROKEN_JSON',
    'nested.jsonl': b'{"id":1,"nested":{"secret":"PRIVATE_NESTED"}}\n{"id":2,"nested":{}}\n',
    'oversized.jsonl': b'{"value":"' + b'x'*1048576 + b'"}\n',
})
cloud_data = {kind:dict(contents) for kind in ('s3','gcs','azure-blob')}
api = GraphApi('synthetic-secret')
for name, content in contents.items():
    (upload / name).write_bytes(content)
    os.chmod(upload / name, 0o644)
    for drive in api.drives:
        api.put(drive, 'retail/' + name, content)
list_ids = ['aaaaaaaa-1111-2222-3333-444444444444', 'bbbbbbbb-1111-2222-3333-444444444444']
for identifier in list_ids:
    api.lists[identifier] = {'columns': ['id', 'label'], 'items': [
        {'id': 1, 'label': 'PRIVATE_PREVIEW'}, {'id': 2, 'label': 'Second List Row'},
        {'id': 3, 'label': 'Third List Row'}]}
requests = []
controls = []


def handle(host, method, target, headers, body):
    url = urlsplit(target)
    if host == '':
        assert method == 'POST' and url.path == '/fixture-control'
        request = json.loads(body)
        assert set(request) == {'action','kind'} and request['kind'] in ('sftp','sharepoint','onedrive','s3','gcs','azure-blob')
        action, kind = request['action'], request['kind']
        assert action in ('schema-broken','schema-duplicate','schema-repair')
        replacement = (b'PRIVATE_BROKEN_JSON' if action == 'schema-broken' else
                       json.dumps([json_rows[0],json_rows[0]]).encode() if action == 'schema-duplicate' else contents['customers.json'])
        if kind == 'sftp':
            (upload/'customers.json').write_bytes(replacement)
            command('docker','cp',str(upload/'customers.json'),container+':/home/reader/upload/customers.json')
        elif kind in ('sharepoint','onedrive'):
            api.put('drive-docs' if kind == 'sharepoint' else 'drive-user','retail/customers.json',replacement)
        else:
            cloud_data[kind]['customers.json'] = replacement
        controls.append(request)
        return 200, {'ok': True}
    requests.append({'host': host, 'method': method, 'path': url.path})
    if host in ('syntheticretail.s3.us-east-1.amazonaws.com','storage.googleapis.com','syntheticretail.blob.core.windows.net'):
        assert method in ('HEAD','GET') and body is None
        kind = 's3' if host.startswith('syntheticretail.s3.') else 'gcs' if host == 'storage.googleapis.com' else 'azure-blob'
        if kind != 'azure-blob':
            assert headers.get('Authorization','').startswith('AWS4-HMAC-SHA256 Credential=SYNTHETIC-KEY/')
        else:
            assert parse_qs(url.query)['sig'] == ['synthetic-secret']
        object_path = unquote(url.path).lstrip('/')
        if kind != 's3': object_path = object_path.partition('/')[2]
        if kind in ('s3','gcs') and not object_path:
            query = parse_qs(url.query)
            assert method == 'GET' and query.get('list-type') == ['2']
            assert query.get('delimiter') == ['/']
            # The runtime first checks for matching descendants of the exact
            # selected key; this fixture contains files, with no descendants.
            assert query.get('prefix') in (['retail/orders.jsonl/'], ['retail/customers.json/'])
            return 200, b'<ListBucketResult><IsTruncated>false</IsTruncated></ListBucketResult>'
        assert object_path.startswith('retail/')
        name = object_path.removeprefix('retail/')
        content = cloud_data[kind].get(name)
        if content is None: return 404,b'PRIVATE_MISSING_OBJECT'
        etag = '"'+hashlib.sha256(content).hexdigest()+'"'
        if kind == 'azure-blob' and method == 'GET': assert headers.get('If-Match') == etag
        return 200,content,{'ETag':etag}
    path = unquote(url.path)
    if host == 'graph.microsoft.com' and path == f'/v1.0/sites/{SITE_ID}/drives':
        assert headers.get('Authorization') == 'Bearer ' + api.token and method == 'GET'
        if parse_qs(url.query).get('$skipToken') == ['library-next']:
            return 200, {'value': [{'id': 'drive-docs', 'name': 'Documents',
                'webUrl': 'https://contoso.sharepoint.com/sites/finance/Shared%20Documents'}]}
        return 200, {'value': [{'id': 'archive-drive', 'name': 'Archive',
            'webUrl': 'https://contoso.sharepoint.com/sites/finance/Archive'}],
            '@odata.nextLink': f'https://graph.microsoft.com{url.path}?$skipToken=library-next'}
    collection = f'/v1.0/sites/{SITE_ID}/lists'
    if host == 'graph.microsoft.com' and path == collection:
        assert headers.get('Authorization') == 'Bearer ' + api.token and method == 'GET'
        query = parse_qs(url.query)
        entries = [
            {'id': list_ids[0], 'name': 'customers', 'displayName': 'Retail Customers', 'list': {'template': 'genericList'}},
            {'id': 'cccccccc-1111-2222-3333-444444444444', 'name': 'Documents', 'list': {'template': 'documentLibrary'}},
            {'id': list_ids[1], 'name': 'orders', 'displayName': 'Retail Orders', 'list': {'template': 'genericList'}},
        ]
        start = int(query.get('$skiptoken', ['0'])[0])
        limit = int(query.get('$top', ['2'])[0])
        page = {'value': entries[start:start + limit]}
        if start + limit < len(entries):
            page['@odata.nextLink'] = f'https://graph.microsoft.com{url.path}?$top={limit}&$skiptoken={start + limit}'
        return 200, page
    if host == 'graph.microsoft.com' and path.startswith(collection + '/') and path.endswith('/columns'):
        return 200, {'value': [
            {'name': 'id', 'number': {'decimalPlaces': 'none'}, 'required': True},
            {'name': 'label', 'text': {}, 'required': True},
        ]}
    return api.handle(host, method, target, headers, body)


def command(*args, timeout=30):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=timeout).strip()


container = None
label = 'folder-inventory-' + uuid.uuid4().hex
key = fixture / 'identity'
# Capture all key tool output; no private key is stored in the acceptance report.
command('ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key))
try:
    assert re.fullmatch(r'sha256:[a-f0-9]{64}', config['sftpImage'])
    container = command('docker', 'create', '--label', 'ingestron.fixture=' + label,
                        '-p', '127.0.0.1::22', config['sftpImage'], 'reader::1001')
    assert re.fullmatch(r'[a-f0-9]{64}', container)
    home = fixture / 'reader'
    keys = home / '.ssh/keys'
    keys.mkdir(parents=True, mode=0o700)
    import shutil
    shutil.copyfile(Path(str(key) + '.pub'), keys / 'fixture.pub')
    shutil.copytree(upload, home / 'upload')
    # Copy synthetic fixture bytes into the container rather than relying on a
    # Desktop host-directory share. No key or data directory is mounted.
    command('docker', 'cp', str(home), container + ':/home/')
    command('docker', 'start', container, timeout=45)
    endpoint = command('docker', 'port', container, '22/tcp')
    assert re.fullmatch(r'127\.0\.0\.1:\d+', endpoint)
    port = int(endpoint.rsplit(':', 1)[1])
    host_key = None
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        probe = subprocess.run(['ssh-keyscan', '-T', '2', '-p', str(port), '-t', 'ed25519', '127.0.0.1'],
                               text=True, capture_output=True, timeout=5)
        for line in probe.stdout.splitlines():
            if not line.startswith('#') and len(line.split()) == 3:
                _, kind, public = line.split()
                host_key = kind + ' ' + public
        if host_key:
            break
        time.sleep(0.2)
    assert host_key, 'Synthetic SFTP server did not become ready'
    config.update(sftpPort=port, sftpHostKey=host_key, fixtureDirectory=str(fixture))
    # Settings mutation is performed by the installed verifier with the CLI YAML parser.
    known = fixture / 'known_hosts'
    known.write_text(f'[127.0.0.1]:{port} {host_key}\n')
    probe = subprocess.run(['sftp', '-i', str(key), '-o', 'IdentitiesOnly=yes', '-o', 'IdentityAgent=none',
                            '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(known),
                            '-P', str(port), '-b', '-', 'reader@127.0.0.1'],
                           input='ls -lan upload\n', text=True, capture_output=True, timeout=15)
    (fixture / 'client-probe.log').write_text(probe.stdout + probe.stderr)
    assert probe.returncode == 0, 'Synthetic SSH server probe failed; see private fixture logs'
    with ExitStack() as stack:
        sites = [site]
        record_python = next((root / '.ingestron/runtimes').glob('*/bin/python'))
        sites.append(Path(subprocess.check_output([str(record_python), '-c',
            'import sysconfig; print(sysconfig.get_paths()["purelib"])'], text=True).strip()))
        servers = [stack.enter_context(loopback(target, handle,
            {'login.microsoftonline.com', 'graph.microsoft.com', 'contoso.sharepoint.com',
             'syntheticretail.s3.us-east-1.amazonaws.com','storage.googleapis.com','syntheticretail.blob.core.windows.net'})) for target in sites]
        server = servers[0]
        config['controlUrl'] = f'http://127.0.0.1:{server.server_port}/fixture-control'
        config_path.write_text(json.dumps(config, indent=2) + '\n')
        env = {**os.environ, 'INGESTRON_GRAPH_FIXTURE_SECRET': 'synthetic-secret',
               'INGESTRON_SFTP_FIXTURE_KEY': key.read_text(),
               'INGESTRON_CLOUD_FIXTURE_SECRET':'synthetic-secret',
               'INGESTRON_CLOUD_FIXTURE_SAS':'sv=2023-11-03&sp=rl&se=2099-01-01&spr=https&sig=synthetic-secret'}
        if config.get('studioScript'):
            command_args = ['node', '--conditions', 'react-server', '--import', 'tsx', config['studioScript'], '--verify', str(config_path)]
            cwd = Path(config['studioScript']).parents[1]
        else:
            command_args = ['node', config['script'], '--verify', str(config_path)]
            cwd = None
        child = subprocess.run(command_args, cwd=cwd, env=env, text=True, capture_output=True, timeout=550)
        sys.stdout.write(child.stdout)
        sys.stderr.write(child.stderr)
        assert child.returncode == 0, 'Installed remote JSON assertions failed'
    proof = Path(config['proof'])
    evidence = json.loads(proof.read_text())
    evidence.update(transportRequests=requests, recoveryControls=controls,
                    fixtureHooksRemoved=all(not (target / 'ingestron_loopback.pth').exists() and
                        not (target / 'ingestron_loopback.py').exists() for target in sites),
                    sftpFixture={'image': config['sftpImage'], 'loopbackOnly': True, 'freshPinnedKey': True})
    assert evidence['fixtureHooksRemoved']
    proof.write_text(json.dumps(evidence, indent=2) + '\n')
finally:
    if container:
        logs = subprocess.run(['docker', 'logs', container], text=True, capture_output=True, timeout=10)
        (fixture / 'server.log').write_text(logs.stdout + logs.stderr)
        actual = command('docker', 'inspect', '--format', '{{index .Config.Labels "ingestron.fixture"}}', container)
        assert actual == label, 'Refuse to remove an unrelated container'
        command('docker', 'rm', '-f', container)
    key.unlink(missing_ok=True)
    Path(str(key) + '.pub').unlink(missing_ok=True)
