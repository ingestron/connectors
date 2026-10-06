# Read-only source methods — local candidate

All 16 portable connector patch candidates declare a connection-test method.
The generated runtime asset map and package locks include the source-owned
`source_access.py`. The public catalogue still points at published versions.

| Connector family                      | Test scope                                    | Source discovery in this candidate                                                  |
| ------------------------------------- | --------------------------------------------- | ----------------------------------------------------------------------------------- |
| SQL Server, PostgreSQL, MySQL, Oracle | Authentication with a constant SELECT         | Bounded table inventory, selected columns and keys                                  |
| Files                                 | Explicit regular file access                  | CSV/TSV headers and Parquet footer; JSON/JSONL require a separate sampling decision |
| Azure Blob, S3, GCS                   | Container/bucket or selected object metadata  | Paged file inventory by prefix/format; selected-file metadata                       |
| SFTP                                  | Pinned-host-key session and working directory | Paged explicit remote folder inventory and selected-file metadata                   |
| SharePoint, OneDrive                  | Site/drive metadata                           | Paged drive folder files and SharePoint list inventory                              |
| Salesforce, HubSpot, Jira             | Authentication/property metadata              | Declared object list and selected property metadata                                 |
| Stripe                                | Account authentication                        | Declared object list and pinned schema; does not prove object permissions           |
| GitHub                                | Configured repository metadata                | Declared Issues object and selected scalar fields from the pinned reader schema     |

Declared object lists and pinned schemas are labelled as declarations. They do
not claim account visibility or live record-derived schema. A passed test only
proves its reported access scope. Unsupported actions fail explicitly; testing
never substitutes a record download.

The private GitHub `1.36.3` candidate declares `source: {stream: issues}` as its
selectable object schema. Inventory returns `DECLARED_OBJECTS`; metadata returns
`DECLARED_SCHEMA`. Of the pinned reader's 29 Issues properties, 20 scalar fields
are supported and nine nested properties are reported as excluded. Metadata
does not read issue records. The installed-candidate CLI and private Studio
walkthrough pass; the public `1.36.0` package is unchanged. Intermediate private
`1.36.2` was rejected during installed qualification because its selectable
object schema was missing; use the corrected candidate for this preview.

The runtime suite tests real protocol branches at the transport boundary, bounded
SQL parameters, header-only files and sanitised errors. Installed Files acceptance
and the authorised Northwind Studio walkthrough are separate evidence. Other
vendors are fixture-tested, not live-cloud qualified.

Protocol references checked on 2026-10-02:
[Azure container properties](https://learn.microsoft.com/en-us/rest/api/storageservices/get-container-properties),
[GitHub repository metadata](https://docs.github.com/en/rest/repos/repos#get-a-repository),
[Stripe account retrieval](https://docs.stripe.com/api/accounts/retrieve),
[S3 HeadBucket](https://docs.aws.amazon.com/AmazonS3/latest/API/API_HeadBucket.html).

## Explicit business-data previews — private candidate

All 16 source packages declare `sample`. Select one source object, optionally choose
its fields, and request 1–50 rows. Database queries apply the row bound on the
server. Salesforce, HubSpot, Jira, Stripe and SharePoint lists request smaller
pages and stop at the probe row. GitHub Issues includes pull requests, matching
the pinned reader; repository context and scalar fields use that reader's schema.

Azure Blob, S3, GCS, SFTP, SharePoint and OneDrive preview one explicit file. Select
a file path; folder expansion is unavailable for previews. The source reader
creates a private temporary download of at most 64 MiB and removes it after the
response. JSON arrays additionally require a file below 1 MB. CSV/TSV, JSONL and
Parquet stop after the requested rows and one truncation probe. A preview has at
most 100 scalar fields, 500 UTF-16 units per displayed value and a 500 KB serialised
budget. Unsupported values or malformed shapes fail explicitly.

Remote `metadata` supports explicit CSV/TSV headers and Parquet schemas using the
same bounded download. It preserves the remote source selection and reads no row
values into the metadata result. SharePoint list metadata comes from column
definitions. JSON/JSONL schema suggestions require the separate, explicit sampling
decision described below. A passed access test still reports only its own scope;
these methods do not turn a test into a record download.

The connector writes no persistent sample output or state. Core retains private
access receipts with field names and row counts; business rows are only in the
requested response. Synthetic protocol checks cover all adapters. Installed Files
and clean-preparation PostgreSQL command/operation/MCP acceptance are separate
checks. Live vendor qualification remains independent. Candidate versions are
explicit in the source-access build, so rebuilds reproduce manifest/runtime bytes.

Run `scripts/source-sample-database-acceptance.py` with the installed CLI entry
point, CLI acceptance script, built local provider, Python 3.12 and an output
directory to create its own loopback PostgreSQL fixture. `--connector mysql` uses
a separate MySQL fixture. The report records the actual database version and
Docker image ID. The runner removes only the container it creates. This is a
synthetic acceptance runner, not a user quickstart.

Protocol references checked on 2026-10-04:
[GitHub repository issues](https://docs.github.com/en/rest/issues/issues),
[Microsoft Graph list items](https://learn.microsoft.com/en-us/graph/api/listitem-list?view=graph-rest-1.0).

## Installed configuration matrix — private candidate

`scripts/configuration-matrix-acceptance.mjs` freezes all 16 source manifests and
runtime assets into independent exact-version fixture tags and installs them
with an immutable CLI/core candidate and a local provider snapshot. It checks
source-owned settings, offline flow preparation, declared actions, fingerprints,
execution permission, missing runtime credentials and private failure receipts.
It also checks GitHub anonymous/token settings and all four SQL Server
credential methods. It launches no source process and makes no vendor requests.

Set `INGESTRON_ACCEPTANCE_CLI_PACKAGE` to the installed CLI package directory,
`INGESTRON_ACCEPTANCE_PROVIDER` to the built local provider,
`INGESTRON_ACCEPTANCE_OUTPUT` to a fresh isolated fixture directory and
`INGESTRON_ACCEPTANCE_PROOF` to the output report. Run the harness with Node 22.
The report records every exact source reference, version, runtime digest and
snapshot commit. Use its passed report for the Studio configuration matrix.
A successful configuration check does not qualify source discovery, samples,
snapshot execution, quality gates or native delivery.

Missing credentials and ordinary source/provider failures retain a **failed**
private receipt. Explicit cancellation or timeout retains **interrupted**.
Receipts from a pre-launch failure contain no settings, credential values or
business records. Correct the reported credential reference before testing
again; an interrupted operation requires inspecting its receipt before retry.

## Browse cloud files — private candidate

S3 1.0.5, GCS 0.1.5 and Azure Blob 2.1.5 declare file inventory. Select a
connection, optionally set `scope: {prefix: "retail/", format: "csv"}`, and
request 1–200 entries. The prefix is literal and includes subfolders; `query`
is a case-insensitive literal substring of the full object path. Omit the scope
or use an empty prefix to browse the configured bucket or container.

Each request reads one bounded listing page. Format and query filters can produce
an empty result with `nextCursor`; keep paging until that cursor is absent.
Use a cursor only with the same connection, prefix, format and query. Restart
browsing after changing those values. Listing is not a frozen inventory snapshot;
objects can change between requests or before the selected file is read.

Inventory returns selectable CSV, TSV, JSON, JSONL and Parquet file paths. It
skips folder markers, Azure directories and other extensions. Files whose paths
cannot be used by the connector are omitted with `UNSUPPORTED_OBJECT_PATH`.
Inventory performs listing requests only and returns no columns or business rows.
Choose a file before requesting metadata or a sample. JSON/JSONL schema
suggestions require explicit sampling options; listing never samples files.

Grant bucket listing permission for S3/GCS and read/list (`rl`) SAS permission
for Azure. A read-only Azure SAS can still read a selected blob, but cannot browse
the container. S3 directory buckets and alternative Azure cloud endpoints are
outside this connector's current endpoint contract.

Protocol references checked on 2026-10-04:
[S3 ListObjectsV2](https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectsV2.html),
[GCS XML object listing](https://cloud.google.com/storage/docs/xml-api/get-bucket-list),
[Azure List Blobs](https://learn.microsoft.com/en-us/rest/api/storageservices/list-blobs).

## Browse SFTP and Microsoft Graph objects — private candidate

SFTP 1.0.7 lists one explicit remote folder. Set `scope.directory` to the folder
and optionally choose a file format. Inventory sorts regular files, returns up to
200 per page and reads no file content. It excludes symlinks and directories.
Folder paths cannot contain wildcards, quotes or traversal. Listing is bounded to
1 MB and 60 seconds; narrow the folder if it exceeds that bound. Restart browsing
if the visible directory metadata changes between pages.

OneDrive 0.1.7 lists one folder; omit `scope.directory` to use the drive root.
SharePoint 0.1.7 file inventory starts at a document library, for example
`scope: {directory: "Shared Documents/retail", format: "csv"}`. Use the library
name alone to list its root. These inventories read one native collection page,
so filtered pages can be empty with a continuation. Continue until `nextCursor`
is absent. File paths in the result can be selected for metadata or a preview.

To browse SharePoint lists, use `scope: {entity: "list"}` with no folder or file
format. Document libraries are excluded. List selections retain the native list
ID as `source: {entity: "list", path: "Lists/<list-id>"}` and display its friendly
name. Selected-list metadata reads column definitions, without reading list
items. File inventory reads names and file metadata without requesting content
or pre-authenticated download URLs. Existing connection credential and permission
requirements apply to every page.

Cursors are bound to the connection and filters. Microsoft Graph continuations
are restricted to the same collection and metadata query parameters; arbitrary
URLs, other sites, folders and list-item endpoints are rejected. Unsupported file
paths are omitted with `UNSUPPORTED_OBJECT_PATH`. JSON/JSONL schema suggestions
require explicit sampling options.

Protocol references checked on 2026-10-04:
[OpenSSH batch and listing commands](https://man.openbsd.org/sftp),
[Graph drive children](https://learn.microsoft.com/en-us/graph/api/driveitem-list-children?view=graph-rest-1.0),
[SharePoint site lists](https://learn.microsoft.com/en-us/graph/api/list-list?view=graph-rest-1.0).

## Verify the private folder candidates

The folder acceptance scripts exercise installed packages with synthetic data.
They use an isolated SFTP server and redirect Microsoft Graph requests to a local
protocol fixture. They do not qualify access to a live Microsoft 365 tenant.

Use Node 22, Python 3.12 and Docker. The fixture in
`test/mocks/sftp-server` pins the ARM image used for local verification. Build it
from that directory and retain its image ID. On another architecture, supply a
compatible SFTP fixture with the same key-only reader setup.

Set these acceptance inputs before running
`scripts/folder-inventory-acceptance.mjs`:

| Variable prefix: `INGESTRON_ACCEPTANCE_` | Value                                                    |
| ---------------------------------------- | -------------------------------------------------------- |
| `CLI_PACKAGE`                            | An immutable installed CLI package directory             |
| `CORE_ARCHIVE`, `CLI_ARCHIVE`            | The exact archives used for that installation            |
| `PROVIDER`                               | The reviewed local provider checkout                     |
| `CACHE`                                  | A prepared, hash-locked Python 3.12 source runtime cache |
| `PYTHON`                                 | The Python 3.12 executable                               |
| `SFTP_IMAGE`                             | The pinned local fixture image ID                        |
| `OUTPUT`, `PROOF`                        | New fixture directory and acceptance report path         |

Put Node 22 and Python 3.12 first in `PATH`. The script freezes the current
connector and provider packages into temporary Git snapshots and installs those
snapshots through the installed core. It browses folders through SDK, CLI and
MCP, discovers selected metadata, writes contract drafts and reads bounded
samples. It then runs three-table snapshots, checks that source and required
quality failures publish no partial output, repairs the source and retries each
recorded run. The SFTP container and fresh key are removed afterwards; fixture
logs and immutable package snapshots remain in the output directory.

The Studio owner has a matching `scripts/folder-inventory-acceptance.ts` script.
It verifies host jobs, reopened drafts, reviewed table registration, bounded
samples, stale/read-only denial and source recovery against the passing installed
fixture. Both scripts keep record values out of durable source receipts and jobs.

SharePoint library resolution in the next private folder candidates follows the
site's drive pages before reading the selected folder. It reads at most 50
metadata pages of 200 drives, rejects repeated or redirected continuations and
requires an unambiguous library on the configured site. The same resolver is used
for inventory, file metadata, samples and ingestion. List searches match both the
internal name and displayed title; selections retain the native list identifier.
See the [Graph drive collection](https://learn.microsoft.com/en-us/graph/api/drive-list?view=graph-rest-1.0)
and [list properties](https://learn.microsoft.com/en-us/graph/api/resources/list?view=graph-rest-1.0).

## Draft remote JSON schemas — private candidate

The private SFTP 1.0.7, SharePoint/OneDrive 0.1.7, S3 1.0.6, GCS 0.1.6 and
Azure Blob 2.1.6 packages declare JSON/JSONL schema sampling in their installed
`metadataOptionsSchema`. Older packages without that declaration still require
an authored contract. SharePoint list metadata continues to read column
definitions without sampling items.

Select one or more explicit files. For `connection_metadata`, pass
`options: {sampleRecords: true, limit: 20}`. The limit accepts 1–50 records;
20 is the default. Without explicit consent, a JSON/JSONL selection fails before
any selected file is downloaded. Invalid options fail before source access.
In Studio, open **Schema discovery options**, enable record sampling, set the
limit, then discover the selected schemas.

Each file uses the existing private download, bounded to 64 MiB. Schema parsing
reads at most 1 MiB and stops after the selected records and one truncation
probe. The result contains field suggestions, the remote file selection, row
count and truncation evidence. It contains no record values or temporary path.
If a later selected file fails, metadata returns no partial table list.

Review every suggestion before ingestion. All suggested fields are nullable and
no unique key is guessed. Scalar integers within int64 and decimals within
precision 38 retain their exact types; nested, mixed, missing-only and unsupported
values require an authored decision. Sampling does not validate the whole file
or prove a required-field, key or quality rule. Author those rules in the draft,
review the flow and validate the full ingestion separately.

To verify the private packages locally, use the same inputs as the folder
acceptance procedure with `scripts/remote-json-schema-acceptance.mjs`. It checks
all six sources through SDK, CLI and MCP, consent and permission denial,
sampled drafts, written Parquet precision, source/quality rejection and same-run
retry. The matching Studio script is
`scripts/remote-json-schema-acceptance.ts`; its `FIXTURE_RUNNER` is the connector
owner's `scripts/remote-json-schema-acceptance.py`. Both use synthetic data,
a fresh loopback SFTP server and fenced cloud/Graph protocol fixtures. Live
vendor qualification remains a separate check.
