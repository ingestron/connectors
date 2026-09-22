"""File-reader adapter for the existing reviewed snapshot workflow."""
import tempfile
from pathlib import Path
import snapshot_runtime as workflow
from files_reader import scan
from singer_bridge import canonical, digest

def file_output(executable, source, catalog, timeout, discover=False, protocol='singer'):
    # A bounded disk spool lets validation finish before any record reaches commit.
    if discover:
        schema, _ = scan(source)
        yield canonical({'streams':[{'tap_stream_id':'records','stream':'records','schema':schema,'metadata':[]}]}).encode()
        return
    selected = next(s for s in catalog['streams'] if s['tap_stream_id']=='records')
    with tempfile.TemporaryFile(mode='w+b') as spool:
        def emit(row):
            line = canonical({'type':'RECORD','stream':'records','record':row}).encode()+b'\n'
            workflow.check(len(line) <= 2_000_000, 'Record exceeds 2 MB')
            spool.write(line)
        schema, _ = scan(source, emit)
        workflow.check(digest(schema) == digest(selected['schema']), 'Source schema changed; rediscover and review')
        yield (canonical({'type':'SCHEMA','stream':'records','schema':schema})+'\n').encode()
        spool.seek(0)
        yield from spool

# The provider's v1 entry point is fixed; only the source transport is replaced.
# Review, approval, provenance, conversion and atomic commits use the same code.
workflow.tap_output = file_output
runtime_identity = workflow.runtime_identity
if __name__ == '__main__': workflow.main()
