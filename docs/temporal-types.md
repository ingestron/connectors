# Portable temporal types — private candidate

The candidate shared extraction bridge accepts reviewed `DATE` and `TIMESTAMP`
contract fields. `DATE` preserves a calendar day. `TIMESTAMP` preserves a value
without a timezone, with microsecond precision. Neither type guesses a timezone,
normalises an offset, truncates fractional digits, or derives a type from text
contents. Timestamp offsets, timezone-aware values and nanosecond Parquet columns
need a separately reviewed mapping; the current candidate rejects them.

Text dates use `YYYY-MM-DD`. Text timestamps include a full date and
`HH:MM:SS`, separated by `T` or a space, with up to six fractional digits.
Invalid calendar values fail without echoing the record. Execution diagnoses
calendar, timestamp format, timezone and precision failures separately, using
fixed source codes and guidance. The local provider discards upstream error text;
CLI/Studio show the safe guidance under their current execution diagnostic. Nullable values retain
nulls; required nulls fail. Temporal projections require a string source schema.

Reviewed CSV, TSV, JSON and JSONL contracts select the temporal parser explicitly.
Parquet metadata can describe native dates and unzoned timestamps with second,
millisecond or microsecond units. Output Parquet uses `date32` and
`timestamp[us]` respectively. The shared quality evaluator compares temporal
`validValues` against exact typed values, alongside null, duplicate and row-count
rules. Invalid listed values cannot match records.

Database metadata now suggests `DATE` for PostgreSQL/MySQL/SQL Server calendar
columns and `TIMESTAMP` for PostgreSQL unzoned timestamps, MySQL `DATETIME`,
Oracle `DATE`/plain timestamps, and SQL Server `datetime`/`smalldatetime`/eligible
`datetime2`. Oracle `DATE` includes a time. SQL Server `timestamp` is a binary
row version and is unsupported by this temporal policy. Database wire schemas
remain JSON strings; only reviewed contracts select native output types.

Oracle zoned timestamps and precision above six digits, and SQL Server
`datetime2(7)`, are excluded from draft fields and rejected before a selected
record read. The driver cannot silently truncate them into a microsecond value.
PostgreSQL zoned timestamps and SQL Server `datetimeoffset` retain their STRING
representation; a naive TIMESTAMP projection rejects their offsets. MySQL
`TIMESTAMP` retains STRING because its session timezone semantics require a
separate policy. Metadata records declared fractional precision where available.

This candidate requires the corresponding installed core and immutable connector
snapshots. Public catalogue aliases are unchanged. Date handling in independently
operated databases, APIs and native targets still requires its own acceptance
matrix; this document does not claim vendor execution or target migrations.
