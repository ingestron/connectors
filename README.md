# Ingestron connectors

Versioned source packages for reviewed ingestion. Install a connector alongside an
execution provider; neither the CLI nor compute providers are bundled here.

With CLI 0.17.4/core 0.12.10, `ingestron provider install local` and
`ingestron connector install <alias>` select these qualified releases: local
provider 0.4.4, Files 1.3.0, SQL Server 1.3.0, Azure Blob 1.2.0 and GitHub
1.34.0. Earlier core versions keep their previously qualified releases.

These releases check ODCS library quality rules (`nullValues`, `missingValues`,
`invalidValues`, `duplicateValues`, `rowCount`) and the key rules implied by
`primaryKey: true` on staged output before commit. A failed `severity: error`
rule stops the run with nothing committed; other rules are recorded in the
snapshot receipt. Reports name rules and counts, never row values. SQL and
engine rules are not evaluated by these connectors.

Files 1.3.0 selects several local CSV, TSV, JSON, JSONL or Parquet files under
one connection. ODCS contracts select output columns and parser types, and
reviewed source-to-target field names carry into the output. See the
[file configuration guide](docs/files.md), [two-file project](examples/files/project.template.yaml)
and [retail training project](examples/retail/README.md). The immutable Files
1.0.1 and 1.1.0 training downloads remain available for older projects. No source
credentials are needed.

Azure Blob 1.2.0 reads the same formats from one selected object, including ADLS
Gen2 files through the Blob endpoint. Execution stays local. See
[Azure Blob configuration](docs/azure-blob.md) for SAS authentication and limits.

SQL Server 1.3.0 reads several selected SQL Server or Azure SQL tables through
one reusable connection with the local provider. ODCS contracts select columns.
It has SQL password and three Microsoft Entra configuration modes. SQL password
was live-qualified on the previous one-table release; the new multi-table path
has synthetic and installed-build evidence. See the [SQL Server guide](docs/sql-server.md)
for the connection choices, type limits and exact install command.

PostgreSQL 1.0.0, MySQL 1.0.0 (also MariaDB) and Oracle 1.0.0 read selected tables
through pure-Python drivers with no native client. They, Files and SQL Server pass
the shared conformance suite, the database connectors against real engines in
local containers. See [PostgreSQL](docs/postgresql.md), [MySQL](docs/mysql.md) and
[Oracle](docs/oracle.md). Every connector declares a reference record (licence,
cost, access, maturity); build new ones with the
[connector kit](docs/adding-connectors.md).

GitHub 1.34.0 reads GitHub.com issues into local Parquet snapshots. It supports
anonymous public reads and explicit token authentication. The pinned Meltano issue
reader supplies schemas and parsing; an Ingestron adapter uses REST for repository
lookup and fails on inaccessible repositories or rejected credentials.

```sh
ingestron provider install local@0.4.4
ingestron connector install github@1.34.0
```

Start with [the public-data tutorial](https://docs.ingestron.io/docs/tutorials/github-to-parquet).
It needs no account or token. See [GitHub configuration](docs/github.md) for limits
and authenticated access. Use CLI 0.17.4 with core 0.12.10, local provider 0.4.4
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
