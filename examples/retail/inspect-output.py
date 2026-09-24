"""Verify the retail snapshot without printing customer rows."""
from pathlib import Path
import subprocess
root=Path(__file__).resolve().parent
python=next((root/'.ingestron/runtimes').glob('*/bin/python'),None)
if python is None:raise SystemExit('Prepare and run the project first.')
code='''
from pathlib import Path
from decimal import Decimal
import pyarrow.parquet as pq
root=Path('.')
tables={}
for name in ['customers','products','orders']:
 files=list((root/'build/generated/data/retail_local').glob('*/retail-001/'+name+'.parquet'))
 assert len(files)==1, 'Complete retail-001 before inspecting output'
 tables[name]=pq.read_table(files[0]).to_pylist()
 assert len(tables[name])==3
prices={p['product_id']:p['unit_price'] for p in tables['products']}
assert all(isinstance(v,Decimal) for v in prices.values())
value=sum(prices[o['product_id']]*o['quantity'] for o in tables['orders'])
assert value==Decimal('61.95')
assert sum(o['quantity'] for o in tables['orders'])==7
assert next(c for c in tables['customers'] if c['customer_id']=='C001')['email'] is None
assert any('\\n' in c['name'] for c in tables['customers'])
print('Verified: 3 customers, 3 products, 3 orders; quantity 7; order value NZD 61.95; nulls and embedded newline preserved.')
'''
subprocess.run([str(python),'-c',code],cwd=root,check=True)
