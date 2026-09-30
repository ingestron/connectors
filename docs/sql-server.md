# SQL Server and Azure SQL tables

Reads named tables from SQL Server or Azure SQL Database into reviewed local
snapshots. One connection serves several tables: each `flows[].tables` entry
names a schema and table, and its ODCS contract chooses the columns. The
connector reads table metadata during discovery and rows after you approve the
contracts. It does not run arbitrary SQL or write to the database.

| Package  | `sql-server@1.5.0`                                                                       |
| -------- | ---------------------------------------------------------------------------------------- |
| Kind     | `sql-server`                                                                             |
| Maturity | verified: conformance suite against SQL Server 2022 in a local container                 |
| Licence  | Adapter Apache-2.0; upstream mssql-python MIT, bundled ODBC binary under Microsoft terms |
| Cost     | No Ingestron charge; database compute and egress charges apply                           |

## Install

```sh
ingestron connector install sql-server@1.5.0
```

The [stand-alone example](../examples/sql-server/project.template.yaml) selects
three product columns and includes a small draft contract.

## Connection

Use a separate account with `SELECT` on the chosen tables and enough metadata
visibility to discover their columns. The machine running the flow needs network
access to the server. The connector requires TLS with certificate validation; it
does not accept a raw connection string or a certificate-bypass setting.

```yaml
packages:
  local: local@0.4.6
  sql-server: sql-server@1.5.0
connections:
  northwind:
    package: sql-server
    sourceId: northwind
    tenantId: training
    settings:
      connection:
        server: example.database.windows.net
        database: northwind
        port: 1433
        authentication:
          method: sql-password
          username: reader
          password:
            $secret:
              env: SQL_READER_PASSWORD
flows:
  - apiVersion: ingestron.flow/v1
    kind: ingestion
    id: northwind_local
    provider: local
    ingestion:
      connection: northwind
      execution: { mode: local }
    tables:
      products:
        source: { schema: dbo, table: Products }
        contract: { $resolve: ./contracts/products.odcs.yaml }
      orders:
        source: { schema: dbo, table: Orders }
        contract: { $resolve: ./contracts/orders.odcs.yaml }
```

Passwords and client secrets must be secret references, resolved only when the
local provider runs. The execution identity is part of the reviewed build, so
changing the connection, a table source or its contract requires a rebuild and
review. Short package names resolve only when the exact release is in
`packages.lock.yaml`, which keeps the full repository, commit and hashes.

| `method`                  | Other settings               | Credential source                                         |
| ------------------------- | ---------------------------- | --------------------------------------------------------- |
| `sql-password`            | `username`, `password`       | SQL login; password is a secret reference                 |
| `entra-default`           | none                         | Azure Identity default chain in the execution environment |
| `entra-managed-identity`  | optional `client_id`         | System or user-assigned managed identity on Azure compute |
| `entra-service-principal` | `client_id`, `client_secret` | Entra application; secret is a secret reference           |

Use `entra-default` for a signed-in local development environment, and a
specific managed identity or service principal for unattended execution. Each
needs a corresponding database user and permissions.

For linked services, Key Vault, integration runtimes or Unity Catalog
connections, use a native Data Factory or Databricks route with the same table
sources (see [source routes](https://docs.ingestron.io/docs/concepts/sources)).

## Tables

| `source` key | Meaning                                                      |
| ------------ | ------------------------------------------------------------ |
| `schema`     | Schema that owns the table, such as `dbo`                    |
| `table`      | Physical table name; spaces and closing brackets are allowed |

The contract can be inline, an ODCS file (`$resolve`) or a reviewed model-pack
definition (`$model: pack:dataset`). It must describe every column you want to
read; there is no second column list. Selected column names must be valid
Ingestron field names (letters, digits and underscores, starting with a letter
or underscore).

## Types

Integers, booleans, decimal and money, floating point, text, uniqueidentifier
and SQL date and time types. Dates and times become ISO text at the current
ODCS and local-snapshot boundary. Review an exact `DECIMAL(precision,scale)`
contract for decimal and money fields so values stay exact. Binary, spatial,
hierarchy, `sql_variant` and other unsupported types fail discovery if selected.

## Behaviour and limits

Reads up to one million rows per table in batches of 1,000 and rejects a larger
table rather than truncating it. A row is capped at 2 MB. Every selected table
is spooled before any record is published, so a failure in a later table
commits nothing. Discovery and execution are separate reads: execution checks
the column schema but does not promise a transactionally consistent or ordered
snapshot across concurrent changes. Use a stable table for reviewed training
runs. Errors name a safe code (`SQL_CONNECT`, `SQL_READ`, `SQL_TABLE`) and never
include source values or credentials.

## Evidence

The shared conformance suite passes against a fake driver and against SQL
Server 2022 Developer in a local container (`pnpm test:containers`; certificate
trust is relaxed for that test only). SQL password was read live against a
Northwind Azure SQL database with 1.0.0. The Entra modes are wired to
Microsoft's driver and pass configuration tests but are not live-qualified.

## References

- [Microsoft mssql-python driver](https://learn.microsoft.com/en-us/sql/connect/python/python-driver-for-sql-server)
  and its [authentication modes](https://learn.microsoft.com/en-us/sql/connect/python/mssql-python/connection-strings)
  (accessed 2026-09-23)
- Its Python code is MIT-licensed. The separately installed `mssql-python-odbc`
  binary has Microsoft distribution terms; review them for your deployment.
- [SQL Server downloads](https://www.microsoft.com/sql-server/sql-server-downloads)
