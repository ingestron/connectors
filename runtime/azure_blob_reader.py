"""Read one bounded Azure blob over HTTPS, then reuse the local format readers."""
import http.client
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, quote
from files_reader import scan as scan_file, MAX_BYTES, require

SAS_FIELDS = {'sv','ss','srt','sp','st','se','sip','spr','sig','sr','si','skoid','sktid','skt','ske','sks','skv','saoid','suoid','scid','ses'}

def request_target(settings):
    account = settings.get('account', '')
    container = settings.get('container', '')
    blob = settings.get('blob', '')
    require(isinstance(account,str) and re.fullmatch(r'[a-z0-9]{3,24}',account), 'Use an Azure public-cloud storage account name')
    require(isinstance(container,str) and re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])',container) and '--' not in container, 'Use a storage container name')
    require(isinstance(blob,str) and 0 < len(blob) <= 1024 and all(ord(c)>=32 and ord(c)!=127 for c in blob) and not blob.startswith('/') and all(p not in ('','.','..') for p in blob.split('/')), 'Use one explicit blob path without traversal or empty segments')
    token = settings.get('sas_token')
    require(isinstance(token,str) and 0 < len(token) <= 8192, 'Set the SAS token through its secret reference')
    try: pairs = parse_qsl(token.lstrip('?'),keep_blank_values=True,strict_parsing=True)
    except ValueError: raise ValueError('Invalid SAS token') from None
    sas = dict(pairs)
    require(len(sas)==len(pairs) and set(sas)<=SAS_FIELDS and all(sas.values()) and all(k in sas for k in ('sv','sp','se','sig')), 'Use a time-limited SAS token with explicit read permissions')
    require('r' in sas['sp'] and set(sas['sp'])<=set('rl') and sas.get('spr')=='https', 'Use an HTTPS-only SAS token with read or read/list permissions')
    return account+'.blob.core.windows.net', '/'+container+'/'+quote(blob,safe='/')+'?'+urlencode(pairs)

def download(settings, destination):
    host,target = request_target(settings)
    deadline=time.monotonic()+60
    connection=None
    try:
        connection=http.client.HTTPSConnection(host,timeout=30)
        connection.request('HEAD',target,headers={'x-ms-version':'2023-11-03'})
        response=connection.getresponse()
        require(response.status==200, 'Azure blob metadata request failed (HTTP '+str(response.status)+'); check access, expiry and path')
        size=response.getheader('Content-Length','')
        etag=response.getheader('ETag','')
        require(size.isdigit() and int(size)<=MAX_BYTES, 'Azure blob exceeds 64 MiB or has no valid length')
        require(etag.startswith('"') and etag.endswith('"') and '\r' not in etag and '\n' not in etag, 'Azure blob has no valid ETag')
        require(response.getheader('x-ms-resource-type')!='directory', 'Select a file, not an ADLS directory')
        response.close();connection.close()
        connection=http.client.HTTPSConnection(host,timeout=30)
        connection.request('GET',target,headers={'x-ms-version':'2023-11-03','If-Match':etag})
        response=connection.getresponse()
        require(response.status==200, 'Azure blob download failed (HTTP '+str(response.status)+'); check access or retry changed input')
        require(response.getheader('ETag')==etag and response.getheader('Content-Length')==size and response.getheader('Content-Encoding') in (None,'identity'), 'Azure blob changed or returned an unsupported encoding')
        total=0
        with destination.open('xb') as out:
            while True:
                require(time.monotonic()<deadline, 'Azure blob download exceeded 60 seconds')
                chunk=response.read(min(65536,MAX_BYTES-total+1))
                if not chunk: break
                total+=len(chunk)
                require(total<=int(size) and total<=MAX_BYTES, 'Azure blob exceeded its declared length')
                out.write(chunk)
        require(total==int(size), 'Azure blob download was incomplete')
    except ValueError:
        raise
    except Exception:
        # Never include URL/query strings, response bodies or transport exception text.
        raise ValueError('Azure blob read failed; check network access and retry') from None
    finally:
        if connection is not None: connection.close()

def scan(settings, emit=None):
    with tempfile.TemporaryDirectory(prefix='ingestron-blob-') as folder:
        path=Path(folder).resolve()/'input'
        download(settings,path)
        return scan_file({'path':str(path),'format':settings['format'],'types':settings.get('types',{})},emit)
