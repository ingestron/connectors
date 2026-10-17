# Local incremental append — private candidate

PostgreSQL, MySQL and Oracle table sources can read bounded batches after a committed integer key. This private candidate is tested with installed packages and a disposable loopback PostgreSQL database. MySQL and Oracle query branches have transport-fixture tests; vendor qualification is separate.

Use a selected, required integer column that is the source table’s sole primary key. The source owner must guarantee rows commit in key order and remain immutable after publication. This mode does not process updates, deletes, late commits below the cursor, timestamp watermarks or CDC. Use snapshot ingestion or a qualified native standard when those semantics are required.

```yaml
# Within an ingestion flow
ingestion:
  connection: sales
  execution: { mode: local, ingestion: incremental }
tables:
  orders:
    source:
      schema: public
      table: orders
      incremental:
        watermark: id
        initial: 0
        batchSize: 100000
        consistency: ordered-committed-append
    # Keep the reviewed ODCS contract here or reference it.
```

Initial cursors must be nonnegative exact JSON integers, no larger than 9007199254740991. Batch size is 1–1000000, default 100000. Runtime cursors support signed 64-bit integers and are returned as exact decimal strings. Queries bind the lower cursor, order by the key and request at most one extra row to report whether another batch is available.

Configure execution and every selected table source together through the private candidate `ingestion_configure` operation or Studio’s reviewed ingestion settings. Mixing snapshot mode with incremental table policies is rejected. Build, prepare the locked runtime, discover, review and approve before execution.

Each successful batch writes Parquet deltas and its next cursor in one atomic commit. Blocking quality failures and interruptions before commit retain the previous cursor. Retry the same run ID after an acknowledgement loss or corrected source failure; committed retries return the same output without rereading the source. A new run ID reads the next batch. Empty batches retain their cursor. `hasMore: false` describes that read, not a promise that no future rows will arrive.

The output namespace includes project, environment, flow and connection identity. A local single-writer lock rejects simultaneous writes. Source, schema, reviewed policy and runtime changes fail with `CHECKPOINT_POLICY`; changed or missing history fails with `CHECKPOINT_HISTORY`. Keep output and receipts together. The private PostgreSQL 1.1.7 candidate supports reviewed compatible runtime upgrades through core 0.12.40, CLI 0.17.18 and local provider 0.4.14. Other migrations and archiving remain unfinished. The current namespace limit is 10000 committed batches.

Run the installed acceptance harness with `scripts/source-sample-database-acceptance.py --workflow incremental` and `cli/scripts/incremental-acceptance.mjs`. It verifies clean preparation, bounded batches, exact cursors, retry hashes, empty changes, a blocking quality failure and recovery without duplicate delivery.

## Preserve a cursor when upgrading the runtime

Retain the previous managed build and approved review before rebuilding the same
output directory with the new packages. Prepare, discover, review and approve the
current build, then use `ingestron checkpoint preview` and `ingestron checkpoint
apply` with the retained build directory and exact review digest. The migration
verifies every existing commit and Parquet file and publishes one immutable
transition under the namespace writer lock. It reads no source records and
resolves no credentials. A stale review writes no transition. Reapplying the same
digest after later batches returns the original transition without changing it.

Only bridge/workflow implementation and package provenance may change. Extraction
settings, credential references, source selection, schema, reviewed projection,
initial cursor, watermark policy, source drivers and dependencies must agree.
These checks live in the installed source runtime, not in the compiler or provider.
The old and new approved source identities remain distinct in their own commits.

The source-level maintenance entry points are `checkpoint_preview` and
`checkpoint_apply` on the locked source CLI. The product route additionally
requires explicit write/execution authority, unchanged managed build scope and
provider acknowledgement. `scripts/checkpoint-migration-acceptance.mjs` verifies
the immutable installed source and product routes against a copied synthetic
PostgreSQL history: IDs 1–2 remain unchanged, then IDs 3–4 and 5 are appended.
Core/CLI retention creates a private baseline of the original managed build and
committed data before upgrade; core verifies its inventory before product
maintenance. MySQL/Oracle migration, Studio controls, backfill,
archive and updates/deletes/CDC remain unfinished.
