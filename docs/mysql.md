# MySQL and MariaDB tables

The MySQL source reads named tables into reviewed local snapshots through
PyMySQL 1.2.3 (MIT). No native database client is needed. One connection can serve
several tables in the same ingestion flow: each `flow.tables` entry names a
schema and table, and its ODCS contract selects the columns. The connector reads
table metadata during discovery and rows after you approve the contracts. It
does not run arbitrary SQL or write to the database.

```sh
ingestron connector install mysql@1.0.0
```

Use an account with `SELECT` on the chosen tables and permission to read their
column metadata. TLS with certificate verification is the default (`tls:
require`); set `tls: disable` only for a local test database.

```yaml
connections:
  sales:
    package: mysql
    sourceId: sales
    tenantId: training
    settings:
      connection:
        host: db.example.internal
        port: 3306
        database: retail
        user: reader
        password:
          $secret:
            env: MYSQL_READER_PASSWORD
flows:
  - apiVersion: ingestron.flow/v1
    kind: ingestion
    id: sales_local
    provider: local
    ingestion:
      connection: sales
      execution: { mode: local }
    tables:
      customers:
        source: { schema: retail, table: customers }
        contract: { $resolve: ./contracts/customers.odcs.yaml }
```

Supported column types: integer types as integers; `decimal`, `float` and `double` as numbers; character, text, `enum`, `set`, dates, times and timestamps as strings. In MySQL the table `schema` is the database name. Other types fail discovery; leave them out
of the contract. Every value is checked against its discovered type, and a table
larger than one million rows fails rather than being truncated.

## Evidence and limits

The shared conformance suite passes against fakes and against a real server in a
local `mysql:8.4` container (`pnpm test:containers`), so the connector is
marked verified. Reads are full snapshots; there is no incremental cursor or
change capture. Errors name a safe code (`DB_CONNECT`, `DB_READ`, `DB_TABLE`) and
never include source values or credentials.
