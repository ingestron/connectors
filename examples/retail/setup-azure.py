"""Create a project for a user's existing Azure retail files; no cloud changes."""
from pathlib import Path
import argparse,re,json
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--account',required=True);p.add_argument('--container',default='samples');p.add_argument('--prefix',default='retail/v1');p.add_argument('--format',choices=['csv','tsv','json','jsonl','parquet'],default='csv')
a=p.parse_args()
if not re.fullmatch(r'[a-z0-9]{3,24}',a.account):p.error('Use the storage account name, not its URL')
if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]',a.container) or '--' in a.container:p.error('Use a valid container name')
if not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*',a.prefix):p.error('Use slash-separated folder names')
root=Path(__file__).resolve().parent;target=root/'project.yaml'
text=(root/'project.template.yaml').read_text().replace('ingestron/connectors/connectors/files/connector.yaml@1.0.1','ingestron/connectors/connectors/azure-blob/connector.yaml@1.0.0').replace('__FORMAT__',a.format)
for name in ['customers','products','orders']:
 old='      path: __'+name.upper()+'_PATH__'
 new=f'      account: {a.account}\n      container: {a.container}\n      blob: {json.dumps(a.prefix+"/"+a.format+"/"+name+"."+a.format)}\n      sas_token:\n        $secret:\n          env: AZURE_STORAGE_SAS'
 assert old in text;text=text.replace(old,new)
with target.open('x') as out:out.write(text)
print('Created project.yaml. Set AZURE_STORAGE_SAS in your environment before discovery or execution.')
