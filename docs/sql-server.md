# SQL Server and Azure SQL tables

The SQL Server source reads named tables into reviewed local snapshots. It
works with SQL Server and Azure SQL Database when the machine running Ingestron
can reach the database. One connection can serve several tables in the same
ingestion flow. Select each physical schema and table under `flow.tables`; the
ODCS data contract selects its columns. The connector reads table metadata
during discovery, then reads rows after you approve the contracts. It does not
run arbitrary SQL or write to the database.

Install the exact source release with:

```sh
ingestron connector install sql-server@1.1.0
```

Use a separate account with `SELECT` permission on the chosen tables and enough
metadata visibility to discover its columns. Give the local machine network
access to the server. The connector requires TLS with certificate validation; it
does not accept a raw connection string or a certificate-bypass setting.

Add the packages, connection and flow tables to your project:

```yaml
packages:
  local: local@0.4.1
  sql-server: sql-server@1.1.0
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

The `connection` block describes the database and local authentication. Each
table's `source` names one physical SQL table. Passwords and client secrets must
be environment references;
they are resolved only when the local provider runs. Do not put their values in
YAML. The execution identity is part of the reviewed build, so changing the
connection, a table source or its contract requires a rebuild and review. Short
package names resolve only when the exact release is installed in
`packages.lock.yaml`; that lock retains the full repository, commit and hashes.

The table contract can be an existing ODCS file instead of an inline definition:

```yaml
tables:
  products:
    source:
      schema: dbo
      table: Products
    contract:
      $resolve: ./contracts/products.odcs.yaml
```

If your project has an installed model pack, `contract: {$model: pack:dataset}`
selects one of its reviewed definitions. The contract must describe every column
you want to read; the SQL connector does not have a second column list. The
[stand-alone example](../examples/sql-server/project.template.yaml) selects three
product columns and includes a small draft contract.

Supported local authentication settings:

| `method`                  | Other settings               | Credential source                                         |
| ------------------------- | ---------------------------- | --------------------------------------------------------- |
| `sql-password`            | `username`, `password`       | SQL login; password is a secret reference                 |
| `entra-default`           | none                         | Azure Identity default chain in the execution environment |
| `entra-managed-identity`  | optional `client_id`         | System or user-assigned managed identity on Azure compute |
| `entra-service-principal` | `client_id`, `client_secret` | Entra application; secret is a secret reference           |

SQL password has been read against the existing Northwind Azure SQL source. The
Entra modes are wired to Microsoft's driver and pass configuration tests, but
have not been live-qualified against an Entra-enabled database identity. They
require a corresponding database user and permissions. Use
`entra-default` for a signed-in local development environment; choose a specific
managed identity or service principal for unattended execution.

The source supports integers, booleans, decimal/money, floating-point, text,
uniqueidentifier and SQL date/time types. Dates and times become ISO text in the
current ODCS/local-snapshot boundary. For decimal or money fields, review an
exact `DECIMAL(precision,scale)` contract so values stay exact. Binary, spatial,
hierarchy, `sql_variant` and other unsupported types fail discovery if selected
in a contract. Use the contract to choose supported fields. Column names selected into an ODCS table
must be valid Ingestron field names (`A-Z`, `a-z`, digits and underscores,
starting with a letter or underscore). Physical SQL table names may include
spaces and closing brackets.

This preview reads up to one million rows per table, in batches of 1,000, and
rejects a larger table after the limit. A row is capped at 2 MB by the local runtime.
Discovery and execution are separate reads. A later execution can see changed
values; it checks column schema but does not promise a transactionally consistent
or ordered snapshot across concurrent source changes. Use a stable source table
for reviewed training runs. The local provider's ordinary approve, retry,
provenance and atomic output rules apply.

ADF and Databricks native connections are future provider bindings. An ADF
linked service may use its managed identity, Key Vault or integration runtime;
a Databricks connection may use its own platform-supported credentials. The SQL
table's `source` choice can remain the same, but these paths require separate
provider implementations and qualification. No native ADF or Databricks execution
is included in this release.

The local adapter uses the pinned
[Microsoft `mssql-python` driver](https://learn.microsoft.com/en-us/sql/connect/python/python-driver-for-sql-server)
and its [documented authentication modes](https://learn.microsoft.com/en-us/sql/connect/python/mssql-python/connection-strings)
(accessed 2026-09-23). Its Python code is MIT-licensed. The separately installed
`mssql-python-odbc` binary has Microsoft distribution terms, which should be
reviewed for your deployment. The source adapter is Apache-2.0, Otrera Limited.
