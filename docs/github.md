# GitHub issues

Reads GitHub issues into reviewed local snapshots through a pinned Singer
reader. The connection names the repositories and how to authenticate; each
`flows[].tables` entry names a stream, and its ODCS contract chooses the
columns. The connector only reads; it never writes to GitHub.

| Package  | `github@1.35.0`                                                      |
| -------- | -------------------------------------------------------------------- |
| Kind     | `github`                                                             |
| Maturity | verified: synthetic loopback checks and a bounded anonymous live run |
| Licence  | Adapter Apache-2.0; upstream MeltanoLabs tap-github Apache-2.0       |
| Cost     | No Ingestron charge; GitHub REST API rate limits apply               |

## Install

```sh
ingestron connector install github@1.35.0
```

Follow [the public-data tutorial](https://docs.ingestron.io/docs/tutorials/github-to-parquet)
for the complete build, review, extraction and retry procedure.
[The example project](../examples/github/project.yaml) uses anonymous
authentication and selects `demo/repo` for local synthetic tests; change that to
`ingestron/cli` for a small live public source.

## Connection

```yaml
connections:
  github:
    package: github
    sourceId: github_issues
    tenantId: demo
    settings:
      authentication: token
      auth_token:
        $secret:
          env: INGESTRON_GITHUB_TOKEN
      repositories:
        - ingestron/cli
flows:
  - apiVersion: ingestron.flow/v1
    kind: ingestion
    id: issues_local
    provider: local
    ingestion:
      connection: github
      execution: { mode: local }
    tables:
      issues:
        source: { stream: issues }
        contract: { $resolve: ./contracts/issues.odcs.yaml }
```

`repositories` lists 1–10 repositories in `owner/name` form; it is the
connection's scope, like a database name. Use the current owner and name: the
REST lookup does not follow repository redirects.

`authentication: anonymous` makes public REST requests without credentials; omit
`auth_token`. GitHub allows 60 unauthenticated requests per hour per originating
IP. `authentication: token` sends the referenced token; use a fine-grained token
limited to the intended repositories with read-only Issues and Metadata access.
Store it in an untracked `.env` file and pass `--secrets-file .env` during
discovery and extraction. A rejected token fails; there is no anonymous
fallback. Ambient GitHub tokens are ignored. When `authentication` is omitted,
token mode is selected if `auth_token` is present. GitHub App and Enterprise
authentication are not supported.

## Tables

| `source` key | Meaning                                        |
| ------------ | ---------------------------------------------- |
| `stream`     | `issues`, across every repository in the scope |

Only `issues` is accepted. Discovery also describes the parent repository. The
issues endpoint includes pull requests.

## Types

Types come from the upstream stream schema: integers, strings, booleans,
numbers and nested JSON values. The contract selects the columns to keep; the
example projects `id` and `title`.

## Behaviour and limits

A missing or inaccessible repository, rejected token, denied permission or rate
limit fails the run with a safe code (`GITHUB_NOT_FOUND`, `GITHUB_AUTH`,
`GITHUB_FORBIDDEN`, `GITHUB_RATE_LIMIT`). A repository with no issues produces a
valid empty snapshot. A completed unchanged retry verifies the existing output
without another source read; incomplete work can need a new extraction. Reads
are full snapshots without event history or incremental changes. Metadata is
limited to 2 MB and upstream messages to 16 MB. No throughput or transactionally
consistent snapshot guarantee is made.

After changing settings, build into a new directory and repeat discovery,
review and approval. Never edit generated review or commit records.

## Evidence

```sh
pnpm install --frozen-lockfile
pnpm runtime:prepare
pnpm validate
pnpm acceptance
```

These use loopback-only synthetic responses and fake credentials and verify
exact rows and failure paths. A bounded anonymous live run against a public
repository passed on 2026-09-30. See [release checks](release.md).

## References

- [GitHub REST API rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
- [GitHub issues REST API](https://docs.github.com/en/rest/issues/issues)
- [MeltanoLabs tap-github](https://github.com/MeltanoLabs/tap-github)
