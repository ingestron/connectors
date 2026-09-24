# Validate and release a source

Use Node 22, pnpm 10.15.0 and Python 3.12 on macOS/Linux.

```sh
pnpm install --frozen-lockfile
pnpm runtime:prepare
pnpm validate
pnpm acceptance
git diff --exit-code -- connectors
```

Validation covers deterministic bundles and digests, runtime identity, ODCS review,
secret references, strict conversions, process failure/timeout and local recovery.
Acceptance uses the actual npm CLI/core and Git-installed local provider with an
upstream issue reader with the Ingestron REST/auth adapter against loopback-only synthetic HTTP. It verifies
pagination, Parquet rows, approval, source-free retry, receipt status and rejection
of changed outputs/projects. No real credentials or live source access are used.

`pnpm runtime:prepare` creates `build/singer-github`. The installed-package gate
creates an independent managed environment. Test transport hooks are outside
hashed source bundles and are never shipped in `connectors/*/runtime.json`.

Each source manifest has its own version, selected in `runtime/connectors.json`.
GitHub 1.33.0 is tagged `github-1.33.0`; installation uses `--tag-prefix github-`.
Never move published tags. package.json is private development tooling, not an
npm package to publish. Its pinned `ingestron` dependency sets the CLI/core pair
used by normal CI; release gates must use the version declared there.

To update Python dependencies, change the explicit requirements input deliberately
and run `uv pip compile runtime/github.in --python-version 3.12 --universal --generate-hashes
--output-file runtime/github.lock`. Review all changes and installed notices,
rebuild source assets, and rerun both gates. The exact upstream source licence is
retained at `runtime/github.license.txt` and in the generated source bundle.
Original Ingestron LICENSE/NOTICE also travel with the runtime. Dependencies are
downloaded separately; their original notices must remain in redistributed images.

After publication, run `INGESTRON_TEST_PUBLIC_SOURCE=1 pnpm acceptance` from an
anonymous fresh checkout of the source tag. Record synthetic, live-cloud and
independent-user evidence separately; one does not establish another.

During host-release qualification only, `INGESTRON_TEST_CLI` can select an explicit
installed CLI executable from a reviewed archive. Record that override as candidate
evidence; it does not establish npm availability. The gate records actual installed
CLI/core/Node versions and verifies the CLI uses its exact declared core. Normal CI
uses the pinned registry dependency and no override.

## Official short names

`catalogue.json` is shared metadata for application adapters, not a package registry
service. CLI 0.13.0 introduces `plugin install github` and `plugin install local`;
older CLIs retain the full-reference commands above. Catalogue changes require no
source-runtime tag. Add a stable release only after its immutable source tag exists
and installed CLI/core/provider acceptance passes. Record the exact core versions
qualified; do not infer compatibility with future core versions. Preserve prior
entries and never change repository/path identities to redirect an existing alias.
The CLI filters compatible releases and stores exact version/commit/file locks.

For a provider candidate, `INGESTRON_TEST_PROVIDER` selects a local tagged Git checkout. Record this separately from public-package evidence.

## Files and retail training

Run `pnpm acceptance:files` for the immutable Files 1.0.1 exercise. It fetches
the already-published `retail-files-1.0.1.zip` and checks its SHA-256 before
running the old three-connection project against the public 1.0.1 tag. The Azure
Blob retail package extends that same verified archive. Do not rebuild either
published download from the current example or move their tags.

Files 1.1.0 moves the file path and format to each flow table and derives parsing
types from the table's ODCS contract. Run `pnpm acceptance:files:tables` with
CLI 0.15.1/core 0.12.4 to check ten files across all five formats through one
connection, discovery, review, stored Parquet rows and rejection of a later
file failure without a partial commit. The published `files-1.1.0` source tag
and shortcut catalogue already point to the qualified connector. Keep the 1.0.1
retail archive and tag unchanged; its acceptance uses the public 1.0.1 tag.

The current [retail example](../examples/retail/README.md) uses Files 1.1.0,
one connection and three contracted tables. `pnpm package:retail` builds
`retail-files-1.1.0.zip` from the unchanged fictional fixture bytes and the
current project/contract files. Run `pnpm acceptance:retail` against that exact
archive and published CLI/core/provider/connector versions. After the gate and
documentation pass, create an immutable `retail-1.1.0` training tag and attach
the tested archive. Keep the source connector tag `files-1.1.0` unchanged.

Source repositories must remain UTF-8 text for the current core host. Parquet fixtures are
base64 text in Git and decoded into the training zip; hashes verify the original
bytes. Files 1.0.0 was not installable from its public tree and is superseded by
1.0.1. Keep that tag immutable and excluded from the qualified catalogue. Candidate
acceptance installs the complete repository tree to catch this boundary.

## Azure Blob retail training

Run `pnpm acceptance:azure-blob` and `python3 scripts/package-azure-retail.py`.
The installed test uses loopback transport with all five formats, conditional-read
and authentication failures, review/approval and recovery. Test-only transport
code never enters runtime bundles. After a qualified `azure-blob-1.0.0` tag,
attach `build/release/azure-blob-retail-1.0.0.zip` and repeat with
`INGESTRON_TEST_PUBLIC_SOURCE=1`. This release reuses core 0.12.1 and local 0.4.1;
its explicit install reference also works with CLI 0.14.0. It has no short CLI alias
yet. Existing public GitHub/files bundles must remain byte-identical.

Live Labs reads are separate, owner-authorised evidence; no cloud credentials or
private endpoints belong in public qualification fixtures.

## SQL Server / Azure SQL

SQL Server 1.1.0 reads several tables through one reusable connection. Its source
tag is `sql-server-1.1.0`; each flow table selects `source.schema` and
`source.table`, and its ODCS contract selects columns. SQL Server 1.0.0 remains
the immutable one-table release. Do not declare an ADF or Databricks execution
capability until a provider binds its native connection and passes installed
acceptance.

The generated bundle pins `mssql-python` 1.15.0, the `mssql-python-odbc` binary
18.6.2.1, Azure Identity and the existing Arrow runtime. Install the SQL lock in
an independent Python 3.12 environment with `--require-hashes` on macOS and
Linux; import both driver and Arrow. Retain the MIT driver licence and note that
the ODBC binary has separate Microsoft terms. This source repo does not bundle
that binary. Review its terms and installed notices before redistributing a
runtime image.

Run `pnpm validate` and the Linux CI lock-install gate. The optional owner-approved
read-only Northwind test is `INGESTRON_SQL_HANDOUT=/absolute/private/connections.json
pnpm acceptance:sql-server:live`. It verifies approval, exact decimal output and
retry. Its generated project, source output and local transcript are ignored under
`build/`. SQL password was live-qualified with 1.0.0; the 1.1.0 multi-table path
has installed synthetic acceptance but awaits a live read. The three Entra modes
have schema/connection construction tests but await live identity qualification.
