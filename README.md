# Ingestron connectors

Versioned source packages for reviewed ingestion. Install a connector alongside an
execution provider; neither the CLI nor compute providers are bundled here.

Files 1.0.0 reads local CSV, TSV, JSON, JSONL and Parquet. Try the
[retail training project](examples/retail/README.md), or read the
[file configuration guide](docs/files.md). No source credentials are needed.

GitHub 1.33.0 reads GitHub.com issues into local Parquet snapshots. It supports
anonymous public reads and explicit token authentication. The pinned Meltano issue
reader supplies schemas and parsing; an Ingestron adapter uses REST for repository
lookup and fails on inaccessible repositories or rejected credentials.

```sh
ingestron plugin install local@0.4.1
ingestron plugin install github@1.33.0
```

Start with [the public-data tutorial](https://docs.ingestron.io/docs/tutorials/github-to-parquet).
It needs no account or token. See [GitHub configuration](docs/github.md) for limits
and authenticated access. Use CLI 0.13.1 or newer with core 0.12.1, local provider
0.4.1 and a prepared Python 3.12 environment on macOS/Linux. CLI 0.13.2 improves
setup guidance and terminal summaries but is not required for anonymous execution.

Synthetic tests cover authentication, pagination, empty results, rate limits,
partial failure and immutable output/retry. A bounded anonymous live run on the
public Ingestron CLI repository also passed; this is not independent-user or
large-volume performance evidence. GitHub Enterprise, other output streams,
incremental sync and cloud execution remain outside this release.

For development, use Node 22 and run `pnpm install --frozen-lockfile`,
`pnpm runtime:prepare`, `pnpm validate` and `pnpm acceptance`.
See [adding sources](docs/adding-connectors.md) and [release instructions](docs/release.md).

Original code is Apache-2.0, licensed by Otrera Limited. See [LICENSE](LICENSE) and
[NOTICE](NOTICE). Upstream Python packages retain their own terms and notices.
Published source tags are immutable; the catalogue preserves older releases.
