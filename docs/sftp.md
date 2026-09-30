# SFTP files

Reads CSV, TSV, JSON, JSONL or Parquet files from an SFTP server into reviewed local snapshots through the machine's OpenSSH `sftp` client. One connection names the server, user, private key and pinned host key; each table names a file or folder and its format. Nothing is written.

| Package  | `sftp@1.0.0`                                                                                   |
| -------- | ---------------------------------------------------------------------------------------------- |
| Kind     | `sftp`                                                                                         |
| Maturity | verified: conformance suite against an SFTP server in a local container                        |
| Licence  | Adapter Apache-2.0; upstream pyarrow Apache-2.0; OpenSSH is used from the machine, not bundled |
| Cost     | None                                                                                           |

## Install

```sh
ingestron connector install sftp@1.0.0
```

## Connection

Authorise a key for a read-only user. Pin the server's host key as `<type> <base64>` (from the administrator, or `ssh-keyscan` checked against a trusted fingerprint). Keep the private key in an environment variable referenced with `$secret`. Password authentication, agents and user SSH configuration are not used.

```yaml
connections:
  source:
    package: sftp
    sourceId: source
    tenantId: training
    settings:
      host: sftp.example.internal
      port: 22
      user: reader
      host_key: ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample
      private_key:
        $secret:
          env: SFTP_PRIVATE_KEY
flows:
  - apiVersion: ingestron.flow/v1
    kind: ingestion
    id: source_local
    provider: local
    ingestion:
      connection: source
      execution: { mode: local }
    tables:
      customers:
        source: { path: exports/customers.csv, format: csv }
        contract: { $resolve: ./contracts/customers.odcs.yaml }
```

## Tables

| `source` key | Meaning                                                                                                                                   |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `path`       | File path (relative to the login directory, or absolute) to read one file, or a folder to read every file of the format directly under it |
| `format`     | `csv`, `tsv`, `json`, `jsonl` or `parquet`                                                                                                |

A folder is one table: its files are read in name order and must share one
schema. Up to 100 files per folder and 64 MiB per file.

## Types

Types come from each table's contract, as for [local files](files.md): string, integer, decimal, number and boolean.

## Behaviour and limits

Each command runs `sftp` in batch mode with strict host-key checking, the pinned key in a private known-hosts file and a 30-second connection timeout. Each file is downloaded, its size checked against the listing, parsed and removed. A changed host key fails with `SFTP_HOST_KEY`; other errors name a code (`SFTP_AUTH`, `SFTP_NOT_FOUND`, `SFTP_NETWORK`, `SFTP_CLIENT` if OpenSSH is missing, and others) and never echo client output or key material.

## Evidence

The shared conformance suite passes against a local transport and against an SFTP server (atmoz/sftp) in a local container with the real OpenSSH client, including a rejected host key and a rejected private key (`pnpm test:containers`).

## References

- [OpenSSH sftp manual](https://man.openbsd.org/sftp)
- [ssh-keyscan manual](https://man.openbsd.org/ssh-keyscan)
