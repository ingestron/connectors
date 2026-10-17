# Installed source journeys — 2026-10-05

All sixteen current source packages pass the synthetic installed CLI journey with
private core 0.12.43, CLI 0.17.18 and local provider 0.4.14. The CLI's declared
public core dependency remains 0.12.14; the tested compiler override is isolated.
This evidence does not establish enterprise readiness.

The matrix exposed a shared compiler defect: a declared source stream was
replaced by the output dataset name. The compiler now preserves the selected
stream while retaining the output name. A renamed GitHub dataset reads `issues`,
reviews successfully and publishes the expected two-row projection. The focused
regression also refuses duplicate streams and selections outside the source
schema. Sources without an explicit stream retain their existing table identity.

| Proof                                 | Result                                                                                                                                                                 |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Preparation](prepare.json)           | Sixteen exact source packages, permission denial and locked source/flow preparation; 48 groups                                                                         |
| [Execution](execute.json)             | Metadata, bounded samples, reviewed Parquet projection/key values/counts, unapproved refusal, publication refusal, recovery and committed source-free retry; 63 groups |
| [Archive parity](archive-parity.json) | All 156 core and 29 CLI archive files match their installed bytes                                                                                                      |
| [Acceptance record](acceptance.json)  | Exact package references, archive hashes, component gates and retained failures                                                                                        |

Core's focused 27 tests and complete 246-test gate pass, including installed
exports and permission boundaries. The connector gate passes five Node tests,
287 Python tests, formatting, build, documentation links and the secret scan.
Default-sandbox listener/IPC failures and their authorised local reruns remain
recorded. No public package was released.

Files use actual synthetic local files. HTTP sources use frozen loopback API
fixtures. Database cases replace DB-API transport; SFTP replaces OpenSSH transport.
The installed connector's validation, metadata, sampling, conversion, snapshot
and retry code stays unchanged. These cases do not qualify real drivers, engines,
SSH, TLS or live vendor accounts.

Fourteen sources reject duplicate contract keys before publication and recover
under the same run identity. Jira rejects repeated source IDs in its reader and
then recovers; its contract-quality failure case remains open. GitHub's quality
failure case also remains open. Static API object/schema declarations keep their
response codes and do not imply account-wide read permission. Samples remain out
of durable receipts and jobs; all test startup hooks were removed.

The execution proof's `allSixteenComplete` field refers only to these sixteen
synthetic source cases. All sixteen product workflow rows remain implementing.
Studio/shared-host/editor adoption of core 0.12.43, browser interaction, native
execution and independent engineer acceptance remain separate work. The existing
Luna preview, its installed compiler and all owner registrations were untouched.

Use [the development matrix guide](../../runtime-matrix.md) to reproduce the
phases. The acceptance record retains fixture pagination/authentication/SQL/SFTP
repairs, the original GitHub failure and test-environment/package-install failures.
