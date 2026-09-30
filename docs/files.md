# Local files

Reads local CSV, TSV, JSON, JSONL and Parquet files into reviewed local
snapshots. One connection serves several tables: each `flows[].tables` entry
chooses its file and format, and its ODCS contract chooses the output columns
and types. The connector does not watch directories or apply incremental
changes.

| Package  | `files@1.4.0`                                                  |
| -------- | -------------------------------------------------------------- |
| Kind     | `local-files`                                                  |
| Maturity | verified: installed runs read real files in every format       |
| Licence  | Adapter Apache-2.0; upstream Apache Arrow (pyarrow) Apache-2.0 |
| Cost     | None                                                           |

## Install

```sh
ingestron connector install files@1.4.0
```

Use [this two-file project](../examples/files/project.template.yaml) as a starting
point. Replace its two absolute path placeholders with your own files before
running `ingestron check`. The [retail exercise](../examples/retail/README.md)
reads three tables through one connection.

## Connection

The connection has no endpoint or credentials; it carries the source and tenant
identity. One flow can read several files, or separate flows can share the
connection when they need independent runs.

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

## Tables

| `source` key | Meaning                                                                     |
| ------------ | --------------------------------------------------------------------------- |
| `path`       | One absolute regular file; URLs, directories, globs, symlinks and `..` fail |
| `format`     | `csv`, `tsv`, `json`, `jsonl` or `parquet`                                  |

The generated project lock binds each path, format and contract to the run.
Moving a file means changing its path, rebuilding and reviewing again.

## Types

Parser types come from each table's contracted columns: string, integer,
decimal, number and boolean. A selected DATE, TIMESTAMP or BINARY column fails
before file access. There is no separate `types` map (since Files 1.1.0). The
contract can select a subset of columns; the reader still validates the complete
flat source schema before publishing selected records.

Delimited files are UTF-8 (an initial BOM is accepted), with a header and
standard double-quoted escaping; TSV uses tabs. Empty delimited fields become
null; other text is preserved. Declare numeric and boolean types in the contract
rather than inferring meaning from identifiers. Integer text must have no
leading zeroes, boolean text is exactly `true` or `false`, and decimals use
exact values, never floats.

JSON is an array of flat objects; JSONL is one object per line. Every row must
have the same fields. Duplicate keys, nested values, blank JSONL records, mixed
undeclared types, malformed rows and non-finite numbers fail. Empty JSON or JSONL
uses the contract columns as its schema; empty CSV or TSV needs headers. Parquet
supports flat strings, integers, decimals, booleans and floating-point fields;
temporal, binary and nested Parquet fields are not yet supported.

## Behaviour and limits

Discovery scans every selected file and reports its complete schema without
changing the contracts. Review projects the selected columns. Extraction
rechecks every source schema and rejects drift. Every selected file is spooled
before any record is published, so a failure in a later file commits nothing.
Changed values with an unchanged schema are a new snapshot with a new run ID;
completed retries verify existing output without rereading input.

Each input is limited to 64 MiB and one million rows, and each output record to
2 MB. JSON arrays are read in memory within that bound; CSV, TSV, JSONL and
Parquet use streamed or batched reads. Leave disk space for input, spool and
Parquet output. File metadata changes during a read fail; supply stable files,
not files with concurrent writers. These are preview bounds, not a throughput
claim.

## Evidence

The shared conformance suite passes, and the installed retail exercise reads
real files in all five formats, with review, rejection, drift and retry checks
(see [release checks](release.md)).

Files 1.0.1 remains immutable with its one-file-per-connection layout. Older
downloaded exercises keep their original layout; installing a new version does
not rewrite their connections or contracts.

## References

- [Python CSV API](https://docs.python.org/3/library/csv.html)
- [Apache Arrow Parquet reader](https://arrow.apache.org/docs/python/parquet.html)
- Original adapter and retail fixtures: Apache-2.0, Otrera Limited. Upstream
  dependency licences remain attached to installed distributions.
