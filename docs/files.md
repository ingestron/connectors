# Read local files

Files 1.0.1 reads one explicitly configured local file per connection. Choose CSV,
TSV, a JSON array, JSON Lines or Parquet. It produces reviewed full snapshots with
the local provider; it does not watch directories or apply incremental changes.

Install the exact connector release:

```sh
ingestron connector install files@1.0.1
```

Use the [retail project](../examples/retail/README.md) to try all five formats.
The same source can be selected by multiple flows; each connection selects one
absolute file path and exposes the `records` stream.

| Setting  | Meaning                                                                                           |
| -------- | ------------------------------------------------------------------------------------------------- |
| `path`   | Absolute local regular file path. No URLs, directories, globbing, symlinks or traversal segments. |
| `format` | `csv`, `tsv`, `json`, `jsonl` or `parquet`.                                                       |
| `types`  | Optional mapping of column names to `string`, `integer`, `decimal`, `number` or `boolean`.        |

Paths are explicit because execution happens in a generated flow directory. The
training setup helper writes your local paths into an ordinary `project.yaml`;
it does not add another project format. Moving the project requires updating
these paths and rebuilding/reviewing it.

Delimited files are UTF-8 (an initial BOM is accepted), with a header and standard
double-quoted escaping. TSV uses tabs. Empty delimited fields become null; other
text is preserved. Declare numeric/boolean types explicitly rather than inferring
meaning from identifiers. Integer text must have no leading zeroes. Boolean text
is exactly `true` or `false`. Decimals use exact text/integer values, never floats.

JSON and JSONL preserve native scalar types; every row must have the same fields.
Duplicate JSON keys, nested arrays/objects, mixed undeclared types, malformed rows
and nonfinite numbers fail. Empty JSON/JSONL needs explicit `types`; empty CSV/TSV
needs headers. Parquet supports flat strings, integers, decimals, booleans and
floating-point fields; temporal, binary and nested fields are not yet supported.

Discovery scans the input and reports its complete schema, without changing your
contract. Review projects selected columns. Extraction rechecks the schema and
rejects drift. Changed values with an unchanged schema are a new snapshot when
using a new run ID. Completed retry verifies existing output without rereading
input. Never use a retry to request new source data.

Each input is limited to 64 MiB and one million rows; each output record to 2 MB.
JSON arrays are read in memory within that file bound. CSV/TSV, JSONL and Parquet
use streamed/batched reads; validated records are spooled to temporary disk before
commit. Leave disk space for input, spool and Parquet output. These are preview
bounds, not a throughput claim. File metadata changes during a read fail; callers
must still supply stable files, not concurrent writers.

The file adapter reuses the existing reviewed snapshot runtime and Apache Arrow.
Its CSV reader follows [Python's CSV API](https://docs.python.org/3/library/csv.html);
Parquet uses [Arrow's batch reader](https://arrow.apache.org/docs/python/parquet.html).
Original adapter and retail fixtures: Apache-2.0, Otrera Limited. Upstream dependency
licences remain attached to installed distributions.
