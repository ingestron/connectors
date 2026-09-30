"""Create a project for the retail files already uploaded to Azure; no cloud changes."""
from pathlib import Path
import argparse
import json
import re
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--account',required=True)
p.add_argument('--container',default='samples')
p.add_argument('--prefix',default='retail/v1')
p.add_argument('--format',choices=['csv','tsv','json','jsonl','parquet'],default='csv')
a=p.parse_args()
if not re.fullmatch(r'[a-z0-9]{3,24}',a.account):p.error('Use the storage account name, not its URL')
if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]',a.container) or '--' in a.container:p.error('Use a valid container name')
if not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*',a.prefix):p.error('Use slash-separated folder names')
root=Path(__file__).resolve().parent
text=(root/'project.template.yaml').read_text().replace('__FORMAT__',a.format)
# One Azure Blob connection holds the account, container and SAS; each table names its blob.
replacements={
 '  files: files@1.2.0':'  azure-blob: azure-blob@2.0.0',
 '  retail_files:\n    package: files\n    sourceId: retail\n    tenantId: training\n    settings: {}':
 f'  retail_blob:\n    package: azure-blob\n    sourceId: retail\n    tenantId: training\n    settings:\n      account: {a.account}\n      container: {a.container}\n      sas_token:\n        $secret:\n          env: AZURE_STORAGE_SAS',
 'connection: retail_files':'connection: retail_blob',
}
for name in ['customers','products','orders']:
 replacements['__'+name.upper()+'_PATH__']=json.dumps(a.prefix+'/'+a.format+'/'+name+'.'+a.format)
for old,new in replacements.items():
 assert text.count(old)==1,old
 text=text.replace(old,new)
with (root/'project.yaml').open('x') as out:out.write(text)
print('Created project.yaml. Set AZURE_STORAGE_SAS in your environment before discovery or execution.')
