# Produce reviewed GitHub issue snapshots

For a developer evaluating Ingestron, this walkthrough produces Parquet containing
issue IDs and titles. It uses a versioned source package, an ODCS contract, explicit
review/approval and a retriable local snapshot. Allow time for the first Python
dependency download; no cloud compute is provisioned.

## Run the repeatable synthetic example

Prerequisites: Git, Node 22, pnpm 10.15.0 and Python 3.12 (on PATH or discoverable
through uv). Work in a disposable checkout:

```sh
git clone --branch github-1.32.1 https://github.com/ingestron/connectors.git
cd connectors
pnpm install --frozen-lockfile
pnpm runtime:prepare
pnpm build
INGESTRON_TEST_PUBLIC_SOURCE=1 pnpm acceptance
```

The test installs npm CLI 0.12.1/core 0.12.0, public local provider 0.4.0 and the tagged
GitHub connector, then runs the unmodified GitHub tap against a loopback fixture.
It temporarily installs a network guard in the disposable Python environment,
rejects external sockets, and removes the guard on completion. No real token is
used. Only dependency downloads and Git package installation require the internet.

Expect two Parquet rows, `1 / Issue 1` and `2 / Issue 2`, and a passing summary for
pagination, approval, retry and tamper/stale rejection. Results and receipts remain
under `build/installed-acceptance`; the test deliberately replaces that disposable
folder on its next run. `build/installed-acceptance/evidence.json` records checks.
This is synthetic qualification, not evidence of successful live GitHub ingestion.

## Configure an authorised GitHub.com repository

This preview procedure uses the same runtime with a live API. It requires a token
with access to the selected repository's issues and metadata. Grant only required
read access; do not use a broad organisation administrator token. API rate limits,
repository permissions and your upstream terms apply. GitHub Enterprise and GitHub
App authentication are not supported by this release.

Install the CLI, then copy the example into a new working directory:

```sh
npm install --global ingestron@0.12.1
mkdir github-project
cp examples/github/project.yaml github-project/project.yaml
cd github-project
```

In `project.yaml`, replace `demo/repo` with your authorised `owner/repository`.
`sourceId` and `tenantId` are non-secret output identity labels; use stable values
for your project. The connection refers to the `github` source package and the
flow's `local` value selects its execution-provider configuration. The ODCS
contract requests only integer `id` and string `title`.

Create an untracked `.env` file containing `INGESTRON_GITHUB_TOKEN=<your token>`.
Add `.env`, `.ingestron/` and `build/` to the project's `.gitignore`. Never put the
token in YAML or command arguments. The tracked YAML stores only its environment
variable reference. Snapshot output can contain repository data: protect the
working directory accordingly.

## Install, build and review

```sh
ingestron plugin install ingestron/provider-local@0.4.0 --cache-only
ingestron plugin install ingestron/connectors/connectors/github/connector.yaml@1.32.1 --tag-prefix github- --cache-only
ingestron check
ingestron build
ingestron runtime prepare
ingestron run --action discover --secrets-file .env
ingestron run --action review
```

Commit `packages.lock.yaml` with your authored configuration. Build creates owned
runtime files without connecting to GitHub. Preparation installs pinned, hash-checked
Python dependencies and can execute upstream build code. Discovery is the first
source operation; a token can be required even when the tap discovers static schemas.
Review is local and produces `build/generated/flows/issues_local/review.json`.

Inspect its source identity, `issues` selection, projected `id`/`title`, and ODCS
contract. Discovery may list additional upstream streams, but this release accepts
only `issues`. Other fields have not been individually qualified; use the supplied
projection for the supported walkthrough. This is a full snapshot, not a guarantee
of a transactionally consistent API view or complete historical issue events.
The tap's issue endpoint can also return pull-request entries; this release does
not filter them out or claim an issues-only business classification.

## Approve, execute and verify

```sh
ingestron run --action approve
ingestron run --run-id issues-001 --secrets-file .env
ingestron run status issues-001
```

Expect a succeeded receipt and table row count. The live result count depends on
your source and API behaviour; it will not equal the synthetic example by design.
Output is under `build/generated/data/issues_local/<identity-hash>/issues-001/`:
`issues.parquet` plus `commit.json`. The hash namespaces the source/tenant labels.
Read back the actual Parquet with the prepared Python environment:

```sh
python3 - <<'PY'
from pathlib import Path
import subprocess
root = Path('.')
python = next((root / '.ingestron/runtimes').glob('*/bin/python'))
files = list((root / 'build/generated/data/issues_local').glob('*/issues-001/issues.parquet'))
assert len(files) == 1
subprocess.run([str(python), '-c', 'import sys,pyarrow.parquet as p;t=p.read_table(sys.argv[1]);print(t.schema);print(t.num_rows)', str(files[0])], check=True)
PY
```

Expect `id` int64 and `title` string; compare the count with `commit.json` and the
CLI receipt. The synthetic acceptance additionally verifies exact row values.

```sh
ingestron run --retry issues-001
```

A completed snapshot is verified and reused without contacting GitHub or requiring
the token. A new run ID requests new extraction. Interrupted work without a valid
commit is retried from the source; no incremental bookmarks are restored.

## Recovery and limits

- **Authentication/rate-limit failure:** check token scope and source availability;
  wait for limits to reset before retrying incomplete work. Upstream retry behaviour
  remains bounded by the flow timeout; diagnostics are withheld to avoid data leaks.
- **Review exists:** preserve the evidence and build into a new output folder for
  a fresh discovery/review. Use the same `--from` on subsequent commands.
- **Schema or generated files changed:** rebuild and review; do not patch runtime
  files or reuse an old run ID against a different build.
- **Committed output changed:** preserve it for investigation. Restore trusted
  original bytes or use a fresh reviewed build/run; do not edit the receipt.

Execution is foreground and sequential on POSIX. There is no scheduler, CDC,
remote cancellation, native ADF/Databricks route or qualified throughput target.
Review supports explicit primitive/decimal projections, not arbitrary nested
objects or automatic date/time coercion. Current runtime bounds include 2 MB
metadata/catalogue, 16 MB upstream messages and 1–100 selected streams globally;
this package further restricts selection to the single supported `issues` stream.

Retain wanted Parquet and receipts before deleting a disposable project. Removing
`.ingestron` also removes its runtime environments and execution receipts.
