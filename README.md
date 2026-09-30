# Ingestron connectors

Versioned source packages for reviewed ingestion. Install a connector alongside an
execution provider; neither the CLI nor compute providers are bundled here.

With CLI 0.17.7/core 0.12.13, `ingestron provider install local` and
`ingestron connector install <name>` select the releases below and local
provider 0.4.5. Earlier core versions keep their previously qualified releases.

These releases check ODCS library quality rules (`nullValues`, `missingValues`,
`invalidValues`, `duplicateValues`, `rowCount`) and the key rules implied by
`primaryKey: true` on staged output before commit. A failed `severity: error`
rule stops the run with nothing committed; other rules are recorded in the
snapshot receipt. Reports name rules and counts, never row values. SQL and
engine rules are not evaluated by these connectors.

| Connector                                      | Package            | Reads                                              | Maturity |
| ---------------------------------------------- | ------------------ | -------------------------------------------------- | -------- |
| [Local files](docs/files.md)                   | `files@1.4.0`      | CSV, TSV, JSON, JSONL, Parquet files               | verified |
| [Azure Blob and ADLS Gen2](docs/azure-blob.md) | `azure-blob@2.0.0` | The same formats from blobs (SAS)                  | preview  |
| [SQL Server and Azure SQL](docs/sql-server.md) | `sql-server@1.4.0` | Tables                                             | verified |
| [PostgreSQL](docs/postgresql.md)               | `postgresql@1.0.0` | Tables                                             | verified |
| [MySQL and MariaDB](docs/mysql.md)             | `mysql@1.0.0`      | Tables                                             | verified |
| [Oracle](docs/oracle.md)                       | `oracle@1.0.0`     | Tables                                             | verified |
| [GitHub](docs/github.md)                       | `github@1.35.0`    | Issues                                             | verified |
| [Stripe](docs/stripe.md)                       | `stripe@0.1.0`     | Customers, charges, invoices and other objects     | preview  |
| [SharePoint](docs/sharepoint.md)               | `sharepoint@0.1.0` | Files and folders in document libraries (Graph)    | preview  |
| [OneDrive](docs/onedrive.md)                   | `onedrive@0.1.0`   | Files and folders in OneDrive for Business (Graph) | preview  |
| [Amazon S3](docs/s3.md)                        | `s3@1.0.0`         | Objects and prefixes (SigV4)                       | verified |
| [Google Cloud Storage](docs/gcs.md)            | `gcs@0.1.0`        | Objects and prefixes (HMAC)                        | preview  |
| [SFTP](docs/sftp.md)                           | `sftp@1.0.0`       | Files and folders (OpenSSH)                        | verified |
| [Salesforce](docs/salesforce.md)               | `salesforce@0.1.0` | Objects (REST, SOQL)                               | preview  |
| [HubSpot](docs/hubspot.md)                     | `hubspot@0.1.0`    | CRM objects                                        | preview  |
| [Jira Cloud](docs/jira.md)                     | `jira@0.1.0`       | Issues, projects, types, statuses, users           | preview  |

Every connector uses the same layout: the connection holds the endpoint, scope
and credentials (always `$secret` references); each `flows[].tables` entry names
one object in the source's terms (`{schema, table}`, `{path, format}`, `{object}` or
`{stream}`); and its ODCS contract chooses the columns and types. One connection
serves several tables. Every connector declares a reference record (licence,
cost, access, maturity) that `ingestron check` shows. Verified means recorded
tests against the real engine or service; preview means conformance against
fakes or mocks. Each page lists its exact evidence.

Start with [the public-data tutorial](https://docs.ingestron.io/docs/tutorials/github-to-parquet)
(no account or token) or the [retail training project](examples/retail/README.md).
Older releases and their downloads remain available at their immutable tags.
Build new connectors with the [connector kit](docs/adding-connectors.md).

For development, use Node 22 and run `pnpm install --frozen-lockfile`,
`pnpm runtime:prepare`, `pnpm validate` and `pnpm acceptance`.
See [adding sources](docs/adding-connectors.md) and [release instructions](docs/release.md).

Original code is Apache-2.0, licensed by Otrera Limited. See [LICENSE](LICENSE) and
[NOTICE](NOTICE). Upstream Python packages retain their own terms and notices.
Published source tags are immutable; the catalogue preserves older releases.
