# Verify the installed source journey

Use this development acceptance matrix to check all sixteen source packages with
an installed CLI, core and local provider. It does not use live source accounts.
The private combinations currently accepted by the harness are CLI 0.17.18 with
core 0.12.42 or 0.12.43; the CLI's public core dependency remains 0.12.14. Supply
both immutable archives and the separately installed candidate.

The matrix freezes source manifests, runtime asset maps, the local provider and
test fixtures. It installs packages from private temporary Git origins with exact
version tags. Runtime code comes from those installed snapshots. The harness
never imports production code from a sibling checkout.

## Run the matrix

Use Node 22 and Python 3.12. Set these environment variables before running
`node scripts/runtime-matrix-prepare.mjs`:

| Variable                            | Value                                                        |
| ----------------------------------- | ------------------------------------------------------------ |
| `INGESTRON_ACCEPTANCE_CLI_PACKAGE`  | Installed `ingestron` package directory                      |
| `INGESTRON_ACCEPTANCE_CORE_ARCHIVE` | Candidate core archive                                       |
| `INGESTRON_ACCEPTANCE_CLI_ARCHIVE`  | Candidate CLI archive                                        |
| `INGESTRON_ACCEPTANCE_PROVIDER`     | Local provider checkout at version 0.4.14                    |
| `INGESTRON_ACCEPTANCE_PYTHON`       | Python 3.12 executable                                       |
| `INGESTRON_ACCEPTANCE_OUTPUT`       | Existing private temporary output directory                  |
| `INGESTRON_ACCEPTANCE_CACHES`       | Optional JSON array of existing dependency-cache directories |

The preparation script prints the new `configPath`. Store that path in
`MATRIX_CONFIG`, then run:

```sh
python3 scripts/runtime-matrix-acceptance.py "$MATRIX_CONFIG" --phase archives
python3 scripts/runtime-matrix-acceptance.py "$MATRIX_CONFIG" --phase prepare
python3 scripts/runtime-matrix-acceptance.py "$MATRIX_CONFIG" --phase execute
```

Archive inspection compares every installed package file with its supplied
archive. Preparation checks all sixteen declared source actions, refusal without
execution permission and exact locked source/flow runtimes. Missing dependency
locks require downloads from the public Python package index.

Execution uses synthetic rows to inspect objects and metadata, request a bounded
sample, reject an invalid limit and an unapproved run, then publish the reviewed
Parquet projection. It verifies field selection, key values and counts, unchanged
output and absence of source transport calls during a committed retry. Duplicate
contract keys fail before publication for fourteen sources. Jira rejects repeated
source IDs earlier in its reader; GitHub's matrix case covers the successful
renamed-dataset journey and retry, without a quality-failure scenario. Corrected
failed runs retry under their original run identity.

Each phase writes its own proof in the temporary matrix directory. Execution
records failures per source and exits unsuccessfully if any selected case fails.
Use `--only github,sftp` for a bounded repair check; a subset cannot count as a
complete sixteen-source matrix.

## Check an installed client

Use the same frozen transports to verify a client without repeating the CLI
execution matrix. Set `INGESTRON_ACCEPTANCE_STUDIO_HOST` to an immutable packaged
Studio `host.cjs`, then run the Studio-owned adapter with private core 0.12.43:

```sh
python3 scripts/runtime-matrix-acceptance.py "$MATRIX_CONFIG" --phase client \
  --client-script ../ingestron-studio/scripts/source-runtime-host-acceptance.mjs
```

The adapter reads a bounded JSON selection and returns a proof for each source.
It starts the actual packaged host, uses the installed CLI and checks metadata,
bounded sampling, trust refusal, current review approval, run results and committed
output previews. Synthetic secret references are supplied through the host's
environment; the browser never receives credentials. Local file fixtures belong
to the generated project so Studio's project-file boundary remains enforced.

The client phase inspects the immutable archives before running and writes
`client-proof.json`. Its `allSixteenClientCasesPassed` flag refers to these source
cases. It does not qualify browser or webview interaction, native delivery or the
sixteen broader product workflows.

## Compiler project identity

The runtime checks compiler-written project locks using a separate UTF-8 codec.
It preserves the compiler's number tokens and key ordering; data, receipts and
checkpoints retain their existing JSON format. The private current-candidate
harness and bounded multilingual journey are recorded in
[compiler project identity evidence](evidence/compiler-project-identity-20261006/README.md).
Its newer archive pair is qualified by the recorded frozen harness; the commands
above describe the separately versioned owning harness.

## Interpret the proof

Files are actual local files. API and object-storage sources use loopback HTTP
fixtures. The database cases replace the DB-API transport, and SFTP replaces the
OpenSSH transport. Their installed connector validation, catalogue, conversion,
sampling, snapshot and retry code runs unchanged. These cases do not qualify a
real database driver or engine, SSH server, TLS connection or vendor account.

Declared API object lists and Stripe's declared schema retain their response
codes. They do not prove permission to read every object. Samples remain in the
immediate response; durable source-access receipts and job records must contain
no row values or credentials. Fixture startup hooks are removed when execution
ends, including after a failed case, and never enter shipped runtime asset maps.

Keep this evidence separate from Studio/browser interaction, MCP/editor parity,
native deployment and independent engineer acceptance. A passing synthetic source
matrix does not establish enterprise readiness.
