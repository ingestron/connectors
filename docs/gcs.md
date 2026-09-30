# Google Cloud Storage objects

Reads CSV, TSV, JSON, JSONL or Parquet objects from a Cloud Storage bucket into reviewed local snapshots through the XML API with HMAC keys. One connection names the bucket and key; each table names an object or prefix and its format. Nothing is written.

| Package  | `gcs@0.1.0`                                                           |
| -------- | --------------------------------------------------------------------- |
| Kind     | `gcs`                                                                 |
| Maturity | preview: conformance suite against a mock                             |
| Licence  | Adapter Apache-2.0; upstream pyarrow Apache-2.0                       |
| Cost     | No Ingestron charge; Cloud Storage operation and egress charges apply |

## Install

```sh
ingestron connector install gcs@0.1.0
```

## Connection

Create an [HMAC key](https://cloud.google.com/storage/docs/authentication/hmackeys) for a service account with read access to the bucket. Keep the secret in an environment variable referenced with `$secret`.

```yaml
connections:
  source:
    package: gcs
    sourceId: source
    tenantId: training
    settings:
      bucket: retail-exports
      access_key_id: GOOGEXAMPLE
      secret_access_key:
        $secret:
          env: GCS_HMAC_SECRET
flows:
  - apiVersion: ingestron.flow/v1
    kind: ingestion
    id: source_local
    provider: local
    ingestion:
      connection: source
      execution: { mode: local }
    tables:
      customers:
        source: { path: v1/customers.csv, format: csv }
        contract: { $resolve: ./contracts/customers.odcs.yaml }
```

## Tables

| `source` key | Meaning                                                                                                             |
| ------------ | ------------------------------------------------------------------------------------------------------------------- |
| `path`       | Object key (or file path) to read one file, or a prefix (folder) to read every file of the format directly under it |
| `format`     | `csv`, `tsv`, `json`, `jsonl` or `parquet`                                                                          |

A prefix is one table: its files are read in name order and must share one
schema. Up to 100 files per prefix and 64 MiB per file.

## Types

Types come from each table's contract, as for [local files](files.md): string, integer, decimal, number and boolean.

## Behaviour and limits

Requests go to `storage.googleapis.com` with path-style addressing and region `auto`, signed like S3 requests. Behaviour, limits and error codes (`GCS_*`) match the [S3 connector](s3.md).

## Evidence

The shared conformance suite passes against an in-memory XML API. The signing path is shared with the S3 connector, which is verified against an S3-compatible server; no live Cloud Storage bucket has been used, so this connector is a preview.

## References

- [Cloud Storage interoperability](https://cloud.google.com/storage/docs/interoperability)
- [HMAC keys](https://cloud.google.com/storage/docs/authentication/hmackeys)
