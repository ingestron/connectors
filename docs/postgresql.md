# PostgreSQL tables

Reads named tables into reviewed local snapshots through pg8000 1.31.5; no
native database client is needed. One connection serves several tables: each
`flows[].tables` entry names a schema and table, and its ODCS contract chooses
the columns. The connector reads table metadata during discovery and rows after
you approve the contracts. It does not run arbitrary SQL or write to the
database.

| Package  | `postgresql@1.0.0`                                                     |
| -------- | ---------------------------------------------------------------------- |
| Kind     | `postgresql`                                                           |
| Maturity | verified: conformance suite against a real server in a local container |
| Licence  | Adapter Apache-2.0; upstream pg8000 BSD-3-Clause                       |
| Cost     | No Ingestron charge; database compute and egress charges apply         |

## Install

```sh
ingestron connector install postgresql@1.0.0
```

## Connection

Use an account with `SELECT` on the chosen tables and permission to read their
column metadata. PostgreSQL is free; use any server the machine running the flow can reach. TLS with certificate verification is the default
(`tls: require`); set `tls: disable` only for a local test database. The
password is always a secret reference.

```yaml
connections:
  sales:
    package: postgresql
    sourceId: sales
    tenantId: training
    settings:
      connection:
        host: db.example.internal
        port: 5432
        database: sales
        user: reader
        password:
          $secret:
            env: PG_READER_PASSWORD
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
        source: { schema: public, table: customers }
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

`smallint`, `integer` and `bigint` as integers; `numeric`, `real`, `double precision` and `money` as numbers; `boolean`; `text`, `character varying`, `character`, `uuid`, dates, times and timestamps as strings. Other types fail discovery; leave them out of the
contract. Every value is checked against its discovered type.

## Behaviour and limits

Reads are full snapshots; there is no incremental cursor or change capture. A
table larger than one million rows fails rather than being truncated. Every
selected table is spooled before any record is published, so a failure in a
later table commits nothing. Errors name a safe code (`DB_CONNECT`, `DB_READ`,
`DB_TABLE`) and never include source values or credentials.

## Evidence

The shared conformance suite passes against fakes and against a real server in a
local `postgres:17-alpine` container (`pnpm test:containers`), with synthetic data
only. The installed end-to-end check (`pnpm acceptance:postgresql`) also passes:
discovery, review, run, unchanged retry and a duplicate key rejected before
commit. That is why the connector is marked verified; it has not been run against
a managed cloud database.

## References

- [pg8000](https://github.com/tlocke/pg8000)
- [PostgreSQL downloads](https://www.postgresql.org/download/)
