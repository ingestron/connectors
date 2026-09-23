# Ingestron connectors

Versioned source packages for reviewed ingestion. Install a connector alongside an
execution provider; neither the CLI nor compute providers are bundled here.

Files 1.1.0 selects several local CSV, TSV, JSON, JSONL or Parquet files under
one connection. ODCS contracts select output columns and parser types. See the
[file configuration guide](docs/files.md) and [two-file project](examples/files/project.template.yaml).
The [retail training project](examples/retail/README.md) remains pinned to Files
1.0.1. No source credentials are needed.

Azure Blob 1.0.0 reads the same formats from one selected object, including ADLS
Gen2 files through the Blob endpoint. Execution stays local. See
[Azure Blob configuration](docs/azure-blob.md) for SAS authentication and limits.

SQL Server 1.1.0 reads several selected SQL Server or Azure SQL tables through
one reusable connection with the local provider. ODCS contracts select columns.
It has SQL password and three Microsoft Entra configuration modes. SQL password
was live-qualified on the previous one-table release; the new multi-table path
has synthetic and installed-build evidence. See the [SQL Server guide](docs/sql-server.md)
for the connection choices, type limits and exact install command.

GitHub 1.33.0 reads GitHub.com issues into local Parquet snapshots. It supports
anonymous public reads and explicit token authentication. The pinned Meltano issue
reader supplies schemas and parsing; an Ingestron adapter uses REST for repository
lookup and fails on inaccessible repositories or rejected credentials.

```sh
ingestron provider install local@0.4.1
ingestron connector install github@1.33.0
```

Start with [the public-data tutorial](https://docs.ingestron.io/docs/tutorials/github-to-parquet).
It needs no account or token. See [GitHub configuration](docs/github.md) for limits
and authenticated access. Use CLI 0.15.1 with core 0.12.4, local provider 0.4.1
and a prepared Python 3.12 environment on macOS/Linux for the current connector
set.

Synthetic tests cover authentication, pagination, empty results, rate limits,
partial failure and immutable output/retry. A bounded anonymous live run on the
public Ingestron CLI repository also passed; this is not independent-user or
large-volume performance evidence. GitHub Enterprise, other output streams,
incremental sync and cloud execution remain outside this release.

For development, use Node 22 and run `pnpm install --frozen-lockfile`,
`pnpm runtime:prepare`, `pnpm validate` and `pnpm acceptance`.
See [adding sources](docs/adding-connectors.md) and [release instructions](docs/release.md).

Original code is Apache-2.0, licensed by Otrera Limited. See [LICENSE](LICENSE) and
[NOTICE](NOTICE). Upstream Python packages retain their own terms and notices.
Published source tags are immutable; the catalogue preserves older releases.
