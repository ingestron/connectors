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

`install(connector)` wires a table connector into the runtime; `install_single(scan)`
wires a single-object connector such as Azure Blob. The GitHub connector uses the
Singer adapter path, which speaks the same runtime contract.

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
