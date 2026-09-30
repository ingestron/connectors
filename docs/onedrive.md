# OneDrive files

Reads CSV, TSV, JSON, JSONL or Parquet files from a user's OneDrive for Business
into reviewed local snapshots through Microsoft Graph. One connection holds the
Entra app credentials and the user; each `flows[].tables` entry names a file
or folder and its format, and its ODCS contract chooses the columns and types.
The connector only reads.

| Package  | `onedrive@0.1.0`                                                                  |
| -------- | --------------------------------------------------------------------------------- |
| Kind     | `onedrive`                                                                        |
| Maturity | preview: unit tests against a Microsoft Graph mock                                |
| Licence  | Adapter Apache-2.0; HTTPS through the Python standard library; pyarrow Apache-2.0 |
| Cost     | No Ingestron charge; Microsoft 365 licensing applies                              |

## Install

```sh
ingestron connector install onedrive@0.1.0
```

## Connection

Register an Entra application with the `Files.Read.All` application permission and
admin consent, and create a client secret. Store the secret in an environment
variable and reference it with `$secret`.

```yaml
connections:
  documents:
    package: onedrive
    sourceId: finance
    tenantId: training
    settings:
      tenant_id: 11111111-2222-3333-4444-555555555555
      client_id: 66666666-7777-8888-9999-000000000000
      client_secret:
        $secret:
          env: GRAPH_CLIENT_SECRET
      user: reader@contoso.com
flows:
  - apiVersion: ingestron.flow/v1
    kind: ingestion
    id: documents_local
    provider: local
    ingestion:
      connection: documents
      execution: { mode: local }
    tables:
      customers:
        source: { path: exports/customers.csv, format: csv }
        contract: { $resolve: ./contracts/customers.odcs.yaml }
      orders:
        source: { path: exports/orders, format: csv }
        contract: { $resolve: ./contracts/orders.odcs.yaml }
```

Only the public cloud (`login.microsoftonline.com`, `graph.microsoft.com`,
`*.sharepoint.com`) and app-only client credentials are supported. There is no
delegated sign-in, certificate credential or sovereign cloud.

## Tables

| `source` key | Meaning                                    |
| ------------ | ------------------------------------------ |
| `path`       | File or folder path from the drive root    |
| `format`     | `csv`, `tsv`, `json`, `jsonl` or `parquet` |

A file path reads that file. A folder path reads every file of the selected
format directly inside it (not subfolders), in name order, and they must share
one schema.

## Types

Types come from each table's contract, as for [local files](files.md): string,
integer, decimal, number and boolean. The [file format rules](files.md#types)
apply.

## Behaviour and limits

Each file is downloaded through Graph's pre-authenticated URL on the tenant's
SharePoint host, its length checked against the item's size, parsed and removed.
Other download hosts and redirects are refused. Every selected table is read
before any record is committed. Limits: 64 MiB and one million rows per file, 100
matching files per folder. Discovery reads the first file only; a run reads them
all. Errors name a safe code (`GRAPH_AUTH`, `GRAPH_FORBIDDEN`, `GRAPH_NOT_FOUND`,
`GRAPH_RATE_LIMIT`, `GRAPH_CHANGED`, `GRAPH_SCHEMA`, `GRAPH_NETWORK` and others)
and never include credentials, tokens or file contents. Throttling fails the
run rather than retrying.

## Evidence

Unit tests pass against an in-memory Microsoft
Graph that follows the documented response shapes (tokens, site and drive
lookup, item paths, paged children, download URLs). No live Microsoft 365
tenant has been used, so the connector is a preview.

## References

- [Client credentials flow](https://learn.microsoft.com/entra/identity-platform/v2-oauth2-client-creds-grant-flow)
- [Get a driveItem by path](https://learn.microsoft.com/graph/api/driveitem-get)
  and [list children](https://learn.microsoft.com/graph/api/driveitem-list-children)
- [Download a file](https://learn.microsoft.com/graph/api/driveitem-get-content)
- [Get a user's drive](https://learn.microsoft.com/graph/api/drive-get)
