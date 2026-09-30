# Azure Blob and ADLS Gen2 files

Reads named CSV, TSV, JSON, JSONL or Parquet blobs into reviewed local snapshots.
One connection names a storage account and container; each `flows[].tables`
entry chooses one blob and its format, and its ODCS contract chooses the columns
and types. ADLS Gen2 files use the account's Blob endpoint. The connector does
not run Azure compute, list folders, expand wildcards or write to storage.

| Package  | `azure-blob@2.0.0`                                                      |
| -------- | ----------------------------------------------------------------------- |
| Kind     | `azure-blob`                                                            |
| Maturity | preview: conformance suite and installed runs against a loopback server |
| Licence  | Adapter Apache-2.0; upstream Apache Arrow (pyarrow) Apache-2.0          |
| Cost     | No Ingestron charge; Azure Storage read and egress charges apply        |

## Install

```sh
ingestron connector install azure-blob@2.0.0
```

## Connection

Store an HTTPS-only, time-limited SAS with read (or read/list) permission on the
container in an environment variable, and reference it with `$secret`. Never put
the token or a signed URL in YAML. The local runtime resolves it at execution
time.

```yaml
connections:
  retail_blob:
    package: azure-blob
    sourceId: retail
    tenantId: training
    settings:
      account: yourstorageaccount
      container: samples
      sas_token:
        $secret:
          env: AZURE_STORAGE_SAS
flows:
  - apiVersion: ingestron.flow/v1
    kind: ingestion
    id: retail_local
    provider: local
    ingestion:
      connection: retail_blob
      execution: { mode: local }
    tables:
      customers:
        source: { path: retail/v1/csv/customers.csv, format: csv }
        contract: { $resolve: ./contracts/customers.odcs.yaml }
      orders:
        source: { path: retail/v1/csv/orders.csv, format: csv }
        contract: { $resolve: ./contracts/orders.odcs.yaml }
```

Only Azure public-cloud account endpoints and SAS authentication are supported.
There is no ambient Azure CLI login, account key, managed identity, sovereign
cloud, custom endpoint or proxy. The machine running the flow must reach the
account; a firewall or private endpoint still controls access. For managed
identity or private networks, use a native Data Factory or Databricks route
(see [source routes](https://docs.ingestron.io/docs/concepts/sources)).

## Tables

| `source` key | Meaning                                                               |
| ------------ | --------------------------------------------------------------------- |
| `path`       | Blob path inside the connection's container; no leading slash or `..` |
| `format`     | `csv`, `tsv`, `json`, `jsonl` or `parquet`                            |

The generated project lock binds each path, format and contract to the run.
Moving a blob means changing its path, rebuilding and reviewing again.

## Types

Types come from each table's reviewed contract, exactly as for
[local files](files.md): string, integer, decimal, number and boolean. A
selected DATE, TIMESTAMP or BINARY column fails before download. There is no
separate `types` map.

## Behaviour and limits

The connector checks each blob's size, downloads it conditionally on its ETag
into a private temporary file and applies the shared file reader. It rejects
redirects, changed or incomplete downloads and compressed HTTP responses, and
removes temporary files after each read. Every selected blob is spooled before
any record is published, so a failure in a later table commits nothing.

The [file reader limits](files.md#behaviour-and-limits) apply per blob: 64 MiB,
one million rows, flat records. Discovery and execution are separate reads;
changed data with the same schema is a new snapshot after review. There is no
version pinning, folder read or change feed.

## Evidence

The shared conformance suite passes against an HTTPS stand-in, and the installed
retail exercise (three tables, five formats, retry, malformed input, drift,
tampering, denied access and changed blobs) passes against a loopback server.
Neither uses a live storage account, so the connector stays preview.

Azure Blob 1.x (one blob per connection, with `blob`, `format` and `types` in the
connection) remains available at its tags; the
[1.1.0 retail download](https://github.com/ingestron/connectors/releases/tag/azure-blob-1.1.0)
keeps that layout. Installing 2.0.0 does not rewrite existing projects.

## References

- [Get Blob](https://learn.microsoft.com/en-us/rest/api/storageservices/get-blob)
  and [conditional requests](https://learn.microsoft.com/en-us/rest/api/storageservices/specifying-conditional-headers-for-blob-service-operations)
  (accessed 2026-09-22)
- [Azure Blob Storage pricing](https://azure.microsoft.com/pricing/details/storage/blobs/)
- Retail exercise: [examples/retail](../examples/retail/README.md) with `setup-azure.py`
