# Local files

Reads local CSV, TSV, JSON, JSONL and Parquet files into reviewed local
snapshots. One connection serves several tables: each `flows[].tables` entry
chooses its file and format, and its ODCS contract chooses the output columns
and types. The connector does not watch directories or apply incremental
changes.

| Package  | `files@1.5.0`                                                  |
| -------- | -------------------------------------------------------------- |
| Kind     | `local-files`                                                  |
| Maturity | verified: installed runs read real files in every format       |
| Licence  | Adapter Apache-2.0; upstream Apache Arrow (pyarrow) Apache-2.0 |
| Cost     | None                                                           |

## Install

```sh
ingestron connector install files@1.5.0
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

## Candidate folder inventory

The private Files 1.5.3 candidate adds `connection_inventory` with an explicit
`scope: {directory: "/absolute/folder", format: "all"}`. The directory must be
local and contain no symlink or traversal components. Browsing reads names and
file attributes, never records; it scans at most 10,000 immediate entries and
returns up to 200 regular CSV, TSV, JSON, JSONL or Parquet files per page.
Subdirectories and symlinks are excluded. Literal name search and format filters
are bound to the returned continuation cursor; changing them starts a new page.
A folder modified while it is listed fails with `ACCESS_CHANGED`.

Select each returned `{path,format}` explicitly for metadata or samples. CSV/TSV
metadata reads headers and Parquet metadata reads the footer. JSON/JSONL schemas
still require explicit sampling or an authored contract: inventory does not infer
them from business records. Samples and snapshot runs retain their existing file
size, row and publication bounds. This candidate has no new official alias.

Run the installed acceptance harness with `pnpm acceptance:files:inventory --cli
<installed-cli> --core-archive <core.tgz> --cli-archive <cli.tgz> --connectors
<source-owner> --provider <local-provider-owner> --cache <qualified-runtime-cache>
--out <synthetic-directory> --proof <proof.json>`. It locks temporary source and
provider snapshots and checks folder scope, all installed client paths, metadata
without record reads, bounded samples, two-table quality, atomic failure and
same-run recovery. The cache must match this platform and exact dependency locks;
`--fresh true` explicitly prepares missing hash-locked dependencies.

### Explicit JSON schema suggestions (private candidate 1.5.4)

Folder browsing still reads no records. JSON/JSONL metadata can explicitly opt in
with `options: {sampleRecords: true, limit: 20}`. The connector reads a prefix of
one selected regular file, at most 1 MiB and 50 reviewed records plus one lookahead
record. The limit defaults to 20. No nested paths, symlinks or recursive folders
are followed. A file changed during the read fails; an oversized prefix or record
fails instead of increasing the limit. The prefix must contain nonempty objects
with matching field names and at most 100 fields.

The returned columns and sample counts are schema suggestions, without record
values. Every sampled field remains optional and has no inferred key. Nested,
mixed, all-null, out-of-int64 or out-of-precision-38 values are left unsupported
with a reason. Explicit scalar `source.types` mappings can resolve compatible
values and all-null fields. Decimal drafts use precision 38 and the observed
scale. Review skipped fields and types before binding the draft; the unread file
suffix and later records have not been validated. Snapshot execution still reads
and validates the complete selected file before publishing its output.

Without options, JSON metadata continues to return `SAMPLING_REQUIRED`.
CSV/TSV headers and Parquet footers keep their existing record-free path even when
JSON sampling options are present. Remote file connectors do not gain inference
through this local Files candidate. No new official alias is declared.

### JSON business previews (private candidate 1.5.5)

Request `connection_sample` for one selected JSON or JSONL file with a row limit
from 1 to 50 and, optionally, up to 100 unique column names. JSON uses a root array
of objects; JSONL uses one object per line. The connector reads at most 1 MiB
plus a one-byte size probe and parses the requested prefix plus one lookahead
record. Files may be up to 64 MiB. A larger unread suffix is not validated by a
preview; full ingestion still validates the complete file.

The sample returns scalar values, exact large integers as strings and decimals
as strings. Cells are limited to 500 characters and the result to 500 KB. Nested
values in selected columns fail the preview; select supported scalar columns
when a record also contains nested fields. No partial sample is returned for a
malformed prefix, mismatched record fields or a file changed during access.
Samples and schema suggestions use the same descriptor and path checks. Business
values appear only in the explicit sample response, never discovery receipts.

### Stable file previews and metadata (private candidate 1.5.6)

CSV, TSV and Parquet access uses the same non-symlink descriptor and before/after
identity checks as JSON and JSONL. A source replaced or modified during access
returns no partial metadata or business preview. CSV/TSV metadata consumes only
the quoted header, up to 64 KiB. Parquet metadata reads the magic bytes and
footer, up to 1 MiB, without fetching data pages; decimal precision and scale
come from the declared schema. Every file in a selected metadata batch must
succeed before the batch is returned.

Business previews read at most 1 MiB plus a one-byte size probe, return at most
50 rows and 100 selected columns, and cap cells at 500 characters and the result
at 500 KB. CSV and TSV support quoted newlines. Parquet reads selected scalar
columns with one thread, without prefetching, and limits selected row groups to
8 MiB of declared uncompressed column data. Large Parquet pages can therefore
require a smaller source file or row group before they can be previewed. These
preview limits are separate from full ingestion. Supported Parquet fields remain
flat scalar types; binary, temporal and nested mappings require separate support.

### Indexed prepared project metadata

The private Files1.5.13 candidate explicitly declares `ingestron.metadata-documents/v1` for prepared project tables. Complete contracts and column metadata use the source-owned document codec: exact hashes and byte counts, safe owned paths, at most100 documents,2MB per document and7MB per collection. Core and the selected provider must also support this format. Existing inline project locks remain supported. This opt-in reuses the existing locked runtime assets; it does not qualify current candidate source access, indexed discovery/review or installed ingestion until their separate acceptance checks pass.
