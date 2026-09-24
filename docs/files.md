# Read local files

Files 1.1.0 reads several local files through one reusable connection. Each
`flows[].tables` entry chooses its file and format; its reviewed ODCS data
contract chooses the output columns and their types. The local provider writes
reviewed full snapshots. This connector does not watch directories or apply
incremental changes.

```sh
ingestron connector install files@1.1.0
```

Use [this two-file project](../examples/files/project.template.yaml) as a starting
point. Replace its two absolute path placeholders with your own files before
running `ingestron check`. One flow can read both files, or separate flows can
share the connection when they need independent runs.

```yaml
connections:
  local_files:
    package: files
    sourceId: retail
    tenantId: training
    settings: {}
flows:
  - apiVersion: ingestron.flow/v1
    kind: ingestion
    id: retail_files_local
    provider: local
    ingestion:
      connection: local_files
      execution: { mode: local }
    tables:
      customers:
        source: { path: /absolute/data/customers.csv, format: csv }
        contract: { $resolve: ./contracts/customers.odcs.yaml }
      orders:
        source: { path: /absolute/data/orders.csv, format: csv }
        contract: { $resolve: ./contracts/orders.odcs.yaml }
```

The connection has no local credentials or endpoint. A `source.path` must name
one absolute regular file; URLs, directories, globs, symlinks and traversal
segments are rejected. `source.format` is `csv`, `tsv`, `json`, `jsonl` or
`parquet`. Moving files requires changing the relevant source paths and
rebuilding/reviewing the flow. The generated project lock binds each path, format
and contract to the run.

There is no separate `types` map in Files 1.1.0. The runtime derives parser
types from each table's contracted columns: string, integer, decimal, number
and boolean are supported. A selected DATE, TIMESTAMP or BINARY column fails
before file access because this file reader has no supported conversion for it.
The contract can select a subset of file columns; the reader still validates
the complete flat source schema before publishing selected records.

Delimited files are UTF-8 (an initial BOM is accepted), with a header and standard
double-quoted escaping. TSV uses tabs. Empty delimited fields become null; other
text is preserved. Declare numeric and boolean types in the ODCS contract rather
than inferring meaning from identifiers. Integer text must have no leading zeroes.
Boolean text is exactly `true` or `false`. Decimals use exact text/integer values,
never floats.

JSON uses an array of flat objects; JSONL uses one object per line. Every row must
have the same fields. Duplicate keys, nested values, blank JSONL records, mixed
undeclared types, malformed rows and nonfinite numbers fail. Empty JSON/JSONL uses
the reviewed contract columns as its declared schema; empty CSV/TSV needs headers.
Parquet supports flat strings, integers, decimals, booleans and floating-point
fields. Temporal, binary and nested Parquet fields are not yet supported.

Discovery scans every selected file and reports its complete schema, without
changing the contracts. Review projects their selected columns. Extraction
rechecks every source schema and rejects drift. The local runtime spools all
selected files before publishing records, so a failed later file cannot commit
partial output from an earlier one. Changed values with unchanged schemas are a
new snapshot with a new run ID; completed retries verify existing output without
rereading input.

Each input is limited to 64 MiB and one million rows; each output record to 2 MB.
JSON arrays are read in memory within that file bound. CSV/TSV, JSONL and Parquet
use streamed/batched reads. Leave disk space for input, spool and Parquet output.
These are preview bounds, not a throughput claim. File metadata changes during a
read fail; callers must still supply stable files, not concurrent writers.

Files 1.0.1 remains immutable and works with its one-file-per-connection layout.
The [current retail exercise](../examples/retail/README.md) uses 1.1.0 and one
connection for three tables. Older downloaded exercises keep their original
layout; installing a new version does not rewrite their connections or contracts.

The file adapter reuses the existing reviewed snapshot runtime and Apache Arrow.
Its CSV reader follows [Python's CSV API](https://docs.python.org/3/library/csv.html);
Parquet uses [Arrow's batch reader](https://arrow.apache.org/docs/python/parquet.html).
Original adapter and retail fixtures: Apache-2.0, Otrera Limited. Upstream dependency
licences remain attached to installed distributions.
