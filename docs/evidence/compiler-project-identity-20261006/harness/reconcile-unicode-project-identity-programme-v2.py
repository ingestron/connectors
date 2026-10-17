from pathlib import Path
import json
b=Path('/Users/sacode/sa.projects/intentlabs/repo/ingestron/repo/.studio-finalisation-20261005');root=b.parent.parent;d=b.parent/'connectors/docs/evidence/compiler-project-identity-20261006';a=json.loads((d/'acceptance.json').read_text());assert a['status']=='passed'
summary='Multilingual contract descriptions now pass the compiler-to-runtime identity check and a real installed local Studio journey. Private CLI 0.17.21/core 0.12.51 and sixteen source candidates preserve the existing data, receipt and checkpoint codecs. Ten 200-column outputs contain thirty measured rows; 2,000 static mapping rows, five exact pages of the 1,237,346-byte review and approval/refusal checks pass. Connectors pass five Node and 291 runtime tests; synthetic checks pass for source preparation (48), the shared host (144) and quality (22). Current archives, owner files and shared assets match their qualified copies. Twenty-table multilingual configurations or reviews exceed existing two-million-byte runtime bounds; the earlier hundred-table validation transport limit also remains open. Clear early scale diagnostics, interactive usability and broader enterprise qualification remain required. All sixteen workflows remain implementing.'
link='[Compiler project identity and bounded multilingual evidence](../../repo/connectors/docs/evidence/compiler-project-identity-20261006/README.md).'
for path in ['docs/product/phase-status.md','docs/solution/shared-studio-delivery.md']:
 p=root/path;s=p.read_text()
 # Both current documents begin with the same readiness paragraph; replace that
 # exact paragraph while preserving the independently qualified prior evidence.
 needle=('Studio now distinguishes a saved review from current preparation.' if 'Studio now distinguishes a saved review from current preparation.' in s else 'Multilingual contract descriptions now pass the compiler-to-runtime identity check')
 start=s.index(needle);end=s.index('\n[Preparation readiness and large review evidence]',start)
 s=s[:start]+summary+'\n'+link+s[end:];p.write_text(s)
p=root/'docs/solution/product-finalisation-acceptance.json';j=json.loads(p.read_text());affected={'connectors','discovery','contracts','estate','snapshot','parity','developer'}
command='Separate compiler project hash fixes multilingual metadata while legacy data/receipt/checkpoint codec bytes remain unchanged. Connectors5Node/291Python/focused4; private CLI21/core51/final frozen host: ten actual200-column outputs/30 measured rows/2000 static mapping rows/80pages/1237346-byte review5 exact SDK-CLI-readonlyMCP pages/whole host reader and approval digest/5 refusal-preservation groups. Fresh all16 synthetic sourceprepare48/host144/quality22/17packages773ownerfiles/runtime156+29/five unchanged shared assets/current52 UI-source-file parity; original8-registration89idle preview preserved. Larger multilingual20table configuration/review failures remain explicit; no mounted/vendor/enterprise qualification.'
for w in j['workflows']:
 if w['id'] in affected:
  assert not any(isinstance(e,dict) and e.get('path')==str(d/'acceptance.json') for e in w['evidence']);w['evidence'].append({'result':'passed','command':command,'path':str(d/'acceptance.json')})
 w['remaining']=[x for x in w.get('remaining',[]) if not x.startswith('Multilingual contract descriptions expose a JavaScript/Python project specification digest mismatch')]
 if w['id'] in {'discovery','contracts','estate'}:
  w['remaining'].append('Twenty-table multilingual configurations or review files exceed the existing two-million-byte runtime bound; preserve fail-closed limits and add bounded preparation/review handling with early, clear UI/CLI diagnostics. Ten200column multilingual outputs and exact approval are installed verified; longer/large multilingual workloads remain unqualified.')
 assert w['status']=='implementing'
assert j['complete']==False and len(j['workflows'])==16;p.write_text(json.dumps(j,indent=2)+'\n')
