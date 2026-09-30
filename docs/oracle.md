# Oracle tables

Reads named tables into reviewed local snapshots through python-oracledb 26.0.1 in thin mode; no
native database client is needed. One connection serves several tables: each
`flows[].tables` entry names a schema and table, and its ODCS contract chooses
the columns. The connector reads table metadata during discovery and rows after
you approve the contracts. It does not run arbitrary SQL or write to the
database.

| Package  | `oracle@1.0.0`                                                         |
| -------- | ---------------------------------------------------------------------- |
| Kind     | `oracle`                                                               |
| Maturity | verified: conformance suite against a real server in a local container |
| Licence  | Adapter Apache-2.0; upstream python-oracledb UPL-1.0 or Apache-2.0     |
| Cost     | No Ingestron charge; database compute and egress charges apply         |

## Install

```sh
ingestron connector install oracle@1.0.0
```

## Connection

Use an account with `SELECT` on the chosen tables and permission to read their
column metadata. Oracle Database Free is available at no cost; use any server the machine running the flow can reach. TLS with certificate verification is the default
(`tls: require`); set `tls: disable` only for a local test database. The
password is always a secret reference.

```yaml
connections:
  sales:
    package: oracle
    sourceId: sales
    tenantId: training
    settings:
      connection:
        host: db.example.internal
        port: 1521
        service: FREEPDB1
        user: reader
        password:
          $secret:
            env: ORACLE_READER_PASSWORD
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
        source: { schema: SALES, table: customers }
        contract: { $resolve: ./contracts/customers.odcs.yaml }
```

For private networks or platform identities, use a native Data Factory or
Databricks route (see [source routes](https://docs.ingestron.io/docs/concepts/sources)).

## Tables

| `source` key | Meaning                    |
| ------------ | -------------------------- |
| `schema`     | Schema that owns the table |
| `table`      | Table name                 |

## Types

`NUMBER` with scale 0 as integers; other `NUMBER`, `FLOAT`, `BINARY_FLOAT` and `BINARY_DOUBLE` as numbers (decimals kept exact); `VARCHAR2`, `NVARCHAR2`, `CHAR`, `NCHAR`, `CLOB`, `NCLOB`, `DATE` and `TIMESTAMP` as strings. Schema names are the owning user, usually upper case. Other types fail discovery; leave them out of the
contract. Every value is checked against its discovered type.

## Behaviour and limits

Reads are full snapshots; there is no incremental cursor or change capture. A
table larger than one million rows fails rather than being truncated. Every
selected table is spooled before any record is published, so a failure in a
later table commits nothing. Errors name a safe code (`DB_CONNECT`, `DB_READ`,
`DB_TABLE`) and never include source values or credentials.

## Evidence

The shared conformance suite passes against fakes and against a real server in a
local `gvenzl/oracle-free:23-slim-faststart` container (`pnpm test:containers`), with synthetic data
only. That is why the connector is marked verified; it has not been run against
a managed cloud database.

## References

- [python-oracledb](https://github.com/oracle/python-oracledb)
- [Oracle Database Free](https://www.oracle.com/database/free/)
