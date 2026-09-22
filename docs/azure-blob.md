# Azure Blob files

Read one CSV, TSV, JSON, JSONL or Parquet object from Azure Blob Storage into a
reviewed local snapshot. ADLS Gen2 files use the account's Blob endpoint. This
connector does not run Azure compute or implement directory, wildcard or incremental
reads. The [file reader limits](files.md) also apply: 64 MiB and one million rows
per object, flat records and explicit decimal types where needed.

Configure the account name, container and blob path separately. Store an HTTPS-only,
time-limited SAS with read (or read/list) permission in an environment variable.
Use a secret reference for `sas_token`; never put the token or a signed URL in YAML.
The local runtime resolves the secret at execution time.

```yaml
settings:
  account: yourstorageaccount
  container: samples
  blob: retail/v1/csv/customers.csv
  sas_token:
    $secret:
      env: AZURE_STORAGE_SAS
  format: csv
  types:
    customer_id: integer
```

The source checks the object size, downloads it conditionally using its ETag, and
then applies the existing file parser. It rejects redirects, changed or incomplete
downloads, and compressed HTTP responses. Temporary input files are removed after
each read. Discovery and execution are separate reads; changed data with the same
schema can be processed after review, as with local files. There is no historical
version pinning or source change feed in this release.

Only Azure public-cloud account endpoints and SAS authentication are supported.
There is no ambient Azure CLI login, account-key, managed identity, sovereign-cloud,
custom-endpoint or proxy configuration. The execution machine must be able to reach
the account. A firewall/private endpoint still controls access.

The adapter uses Python HTTPS and the documented
[Get Blob API](https://learn.microsoft.com/en-us/rest/api/storageservices/get-blob)
and [conditional requests](https://learn.microsoft.com/en-us/rest/api/storageservices/specifying-conditional-headers-for-blob-service-operations)
(accessed 2026-09-22). Existing pinned Arrow readers and reviewed snapshot code
remain shared with the files package.
