# Add a connector with the connector kit

This repository owns source manifests, settings, discovery and runtime adapters.
An execution provider owns compute and platform assets, including native platform
connectors. Core owns the common package and operation schemas.

## Start from the scaffold

```sh
pnpm connector:new <id> --label "Display name"
pnpm runtime:test
```

The scaffold creates a working example connector (one JSON Lines file per table),
a conformance test and a documentation page. The example passes the conformance
suite as generated; replace it with the real source and keep the suite passing.

## The connector interface

`runtime/connector_kit.py` defines the interface. A table connector implements:

| Method                        | Purpose                                                                                   |
| ----------------------------- | ----------------------------------------------------------------------------------------- |
| `settings(settings)`          | Validate the connection settings; secret references are already resolved                  |
| `table(source, columns)`      | Validate one table's source settings; return what `scan` needs                            |
| `scan(settings, table, emit)` | Return the table's JSON Schema; when `emit` is given, also call `emit(row)` for every row |

Declare `table_keys` (the table source settings) and `errors` (safe codes and
messages). Raise `kit.SourceError(code)` for failures users can act on. Messages
must never contain source values or credentials.

The kit owns everything else: locked-project checks, table and column bounds,
secret resolution, spooling every table before any record reaches commit,
schema-drift checks, review of every selected table, and error codes. The shared
runtime then owns projection to the reviewed contract, type conversion, quality
rules, atomic commit and receipts. Connectors never write outputs or state.

`install(connector)` wires a table connector into the runtime. The GitHub
connector uses the Singer adapter path, which speaks the same runtime contract.

## Connection and table settings

Every connector splits its settings the same way, so a flow reads alike across
sources and a native provider route can reuse the table sources:

| Where                          | Holds                                | Examples                                                    |
| ------------------------------ | ------------------------------------ | ----------------------------------------------------------- |
| Connection `settings`          | Endpoint, scope and credentials      | host, database, account, container, SAS                     |
| `flows[].tables.<name>.source` | One object in the source's own terms | `{schema, table}`, `{path, format}`, `{object}`, `{stream}` |
| The table's ODCS contract      | Columns, types and quality rules     | never a second column list or `types` map                   |

Declare the connection shape as `definition.settingsSchema` and the table shape
as `definition.tableSourceSchema`. Credentials are always `$secret` references.

## Conformance

`test/conformance/harness.py` is one suite every table connector passes before
release: deterministic discovery of every table, schemas before records, empty
tables, drift failing before any record, a failure in the last table publishing
nothing, errors free of secrets and source values, and locked-project bounds. A
fixture supplies settings, tables, rows and ways to change or break the source.
Files and SQL Server run it against fakes; PostgreSQL, MySQL, Oracle and SQL Server
also run it against real engines in local containers:

```sh
pnpm test:containers        # Docker required; synthetic data only
```

## Connector page

Each `docs/<id>.md` uses the same sections: a one-paragraph summary, a table of
package, kind, maturity, licence and cost, then **Install**, **Connection**
(with a `connections` and `flows` example), **Tables** (the `source` keys),
**Types**, **Behaviour and limits**, **Evidence** and **References**. The
scaffold creates this outline.

## API mocks

Connectors for services without a free local engine are tested against
in-memory mocks in `test/mocks/` that follow the vendor's published API
(pagination, authentication, error bodies). The conformance fixture patches the
reader's HTTPS connection with the mock; `test/mocks/loopback.py` serves the same
mock to an installed runtime so the CLI path runs end to end
(`pnpm acceptance:apps`). Mocks never ship in runtime assets. A connector tested
only against mocks stays `preview`.

## Maturity and reference records

Every connector carries a reference record in `src/sources.mjs`: documentation,
licence, cost, access, authentication, network, maturity and the date it was
checked. Start at `preview` (conformance against fakes or mocks). Move to
`verified` only with recorded tests against the real service, such as a local
container of the real engine or a free or test account. `qualified` needs native
platform execution or an independent user.

## Packaging

Add a build entry (see `scripts/build-database.mjs`), exact requirements in
`runtime/<id>.in` compiled to a hash-locked `runtime/<id>.lock` with
`uv pip compile --generate-hashes`, and the upstream licence text. Keep package
versions independent. Wrapped ecosystem connectors (Singer, Airbyte, dlt) are
added one at a time with their own licence evidence; restricted licences such as
ELv2 are candidates only until legal review.

## Testing against unreleased core and CLI

```sh
INGESTRON_TEST_CLI=$(pnpm -s local-stack --print) pnpm acceptance:files:tables
```

`pnpm local-stack` packs core and the CLI from the sibling checkouts and installs
them together, with the CLI declaring exactly that core, so installed gates run
without publishing to npm.
