# SQL Server and Azure SQL tables

The SQL Server source reads one named table into a reviewed local snapshot. It
works with SQL Server and Azure SQL Database when the machine running Ingestron
can reach the database. Choose a schema, table and optionally a list of columns.
The connector reads table metadata during discovery, then reads the rows after
you approve the ODCS contract. It does not run arbitrary SQL or write to the
database.

Install the exact source release with:

```sh
ingestron connector install sql-server@1.0.0
```

Use a separate account with `SELECT` permission on the chosen table and enough
metadata visibility to discover its columns. Give the local machine network
access to the server. The connector requires TLS with certificate validation; it
does not accept a raw connection string or a certificate-bypass setting.

One project's connection settings look like this:

```yaml
connections:
  products:
    package: sql-server
    sourceId: northwind_products
    tenantId: training
    settings:
      object:
        schema: dbo
        table: Products
        columns: [ProductID, ProductName, UnitPrice]
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
```

The `object` block is the source choice. The `connection` block binds it to
local execution. Passwords and client secrets must be environment references;
they are resolved only when the local provider runs. Do not put their values in
YAML. The execution identity is part of the reviewed build, so changing the
connection or auth method requires a rebuild and review.

The table contract can be an existing ODCS file instead of an inline definition:

```yaml
tables:
  products:
    source:
      stream: records
    contract:
      $resolve: ./contracts/products.odcs.yaml
```

If your project has an installed model pack, `contract: {$model: pack:dataset}`
selects one of its reviewed definitions with core 0.12.2 or later. The contract
must describe the columns selected by `object.columns`; remove that filter to
read a complete table contract. The stand-alone example selects three columns
and includes a small draft contract so it works without a separate model pack.

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
hierarchy, `sql_variant` and other unsupported types fail discovery; use
`columns` to choose the fields you need. Column names selected into an ODCS table
must be valid Ingestron field names (`A-Z`, `a-z`, digits and underscores,
starting with a letter or underscore). Physical SQL table names may include
spaces and closing brackets.

This preview reads up to one million rows, in batches of 1,000, and rejects a
larger table after the limit. A row is capped at 2 MB by the local runtime.
Discovery and execution are separate reads. A later execution can see changed
values; it checks column schema but does not promise a transactionally consistent
or ordered snapshot across concurrent source changes. Use a stable source table
for reviewed training runs. The local provider's ordinary approve, retry,
provenance and atomic output rules apply.

ADF and Databricks native connections are future provider bindings. An ADF
linked service may use its managed identity, Key Vault or integration runtime;
a Databricks connection may use its own platform-supported credentials. The SQL
source's `object` choice can remain the same, but these paths require separate
provider implementations and qualification. No native ADF or Databricks execution
is included in this release.

The local adapter uses the pinned
[Microsoft `mssql-python` driver](https://learn.microsoft.com/en-us/sql/connect/python/python-driver-for-sql-server)
and its [documented authentication modes](https://learn.microsoft.com/en-us/sql/connect/python/mssql-python/connection-strings)
(accessed 2026-09-23). Its Python code is MIT-licensed. The separately installed
`mssql-python-odbc` binary has Microsoft distribution terms, which should be
reviewed for your deployment. The source adapter is Apache-2.0, Otrera Limited.
