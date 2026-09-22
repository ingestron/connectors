# Read GitHub issues

Follow [the public-data tutorial](https://docs.ingestron.io/docs/tutorials/github-to-parquet)
for downloads and the complete build, review, extraction and retry procedure.
[The example project](../examples/github/project.yaml) uses anonymous authentication.
For local synthetic tests it selects `demo/repo`; change that to `ingestron/cli`
for a small live public source.

## Authentication

`authentication: anonymous` makes public REST requests without credentials. Omit
`auth_token`. Ambient GitHub tokens are ignored. GitHub's unauthenticated allowance
is 60 requests per hour per originating IP; see [GitHub's rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).

For authenticated access, set `authentication: token` and:

```yaml
auth_token:
  $secret:
    env: INGESTRON_GITHUB_TOKEN
```

Store the value in an untracked `.env` file and pass `--secrets-file .env` during
discovery/extraction. Use a token restricted to the intended repository with
read-only Issues and Metadata access. A rejected token fails; there is no anonymous
fallback. Omitted authentication selects token mode when `auth_token` is present,
otherwise anonymous mode. GitHub App and Enterprise authentication are unsupported.

After changing settings, build into a new directory and repeat discovery, review
and approval. Preserve the old output and use the same `--from` throughout each
workflow. Never edit generated review or commit records to bypass integrity checks.

## Behaviour and limits

Only `issues` is accepted as an output stream. Discovery also describes the parent
repository. The issues endpoint includes pull requests. The example projects `id`
and `title`; it does not extract an event history or incremental changes.

A missing/inaccessible repository, rejected token, denied permission or rate limit
fails the run. An accessible repository with no issues produces a valid empty
snapshot. A completed unchanged retry verifies the existing output without another
source read. Incomplete work can require a new extraction.

The REST lookup does not follow repository redirects: use the current owner/name.
The runtime limits metadata to 2 MB and upstream messages to 16 MB. Dependency
versions/hashes and reviewed identities are checked before execution. No throughput
or transactionally consistent snapshot guarantee is made.

## Repeatable developer check

```sh
pnpm install --frozen-lockfile
pnpm runtime:prepare
pnpm validate
pnpm acceptance
```

These use loopback-only synthetic responses and fake credentials. They verify
exact rows and failure paths; they do not make live GitHub source calls. Public
package downloads still need network access. See [release checks](release.md).
