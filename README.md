# Ingestron connectors

Versioned source packages for reviewed Ingestron ingestion. Install the source you
need alongside an execution provider; sources do not bundle the CLI or platform
providers.

| Package       | Supported route                                   | Qualification                                                                        |
| ------------- | ------------------------------------------------- | ------------------------------------------------------------------------------------ |
| GitHub 1.32.0 | GitHub.com issues → local Parquet, full snapshots | Installed CLI/core/provider, unmodified upstream tap against synthetic loopback HTTP |

Use Node 22, Ingestron CLI 0.12.1/core 0.12.0, local provider 0.4.0 and Python 3.12 on
macOS/Linux. GitHub Enterprise, other streams, incremental sync, cloud execution
and performance guarantees are outside this preview.

Start with the [GitHub walkthrough](docs/github.md). It includes an executable
synthetic test with exact expected rows; no GitHub credentials are needed for that
route. The live-source procedure requires your own authorised repository and token
and has not been independently qualified against the live GitHub API.

```sh
ingestron plugin install ingestron/provider-local@0.4.0 --cache-only
ingestron plugin install ingestron/connectors/connectors/github/connector.yaml@1.32.0 --tag-prefix github- --cache-only
```

Use these commands inside the example project. Each connector has its own exact
manifest version and tag prefix. Installing GitHub does not install other sources.
Python dependencies download only during explicit runtime preparation.

Original code is Apache-2.0, licensed by Otrera Limited. Upstream connector and
Python dependency terms/notices remain separate. See [LICENSE](LICENSE),
[NOTICE](NOTICE) and [release instructions](docs/release.md).

For development, run `pnpm install --frozen-lockfile`, `pnpm runtime:prepare`,
`pnpm validate`, and `pnpm acceptance`. See [adding sources](docs/adding-connectors.md).
