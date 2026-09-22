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
npm package to publish. `ingestron@0.13.2` is a pinned development/test dependency.

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

Run `pnpm acceptance:files` and `pnpm package:retail`. The files source tag is
`files-1.0.0`; attach `build/release/retail-files-1.0.0.zip` to that release after
qualification. `INGESTRON_TEST_PUBLIC_SOURCE=1 pnpm acceptance:files` verifies
the public tag. The immutable zip contains a pinned fixture subset and its licence,
not private demo infrastructure. Keep fixture bytes unchanged; verify provenance
before packaging. CSV, TSV, JSON, JSONL and Parquet all pass the same retail checks.
