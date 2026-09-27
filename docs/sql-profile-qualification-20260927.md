# SQL multi-table execution qualification

Date: 2026-09-27. Candidate SQL Server connector 1.2.0, source commit
`133d5aa`, local provider 0.4.3 (`0ea6783`), core 0.12.7 candidate.

A fresh installed-package project used immutable manifest commits from local Git
checkouts. The owner authorised the existing read-only Northwind demo connection.
Credentials stayed in a private host handout and child environment.

Check, local build, Python 3.12 runtime preparation, discovery, review, approval
and extraction succeeded. Customers produced 91 rows and Orders 830 rows, using
four authored columns including the `CustomerID` to `customer_id` rename and
nullable decimal Freight. The same datasets/contracts generated 13 ADF assets
under a named execution profile. No native ADF run or deployment was performed.

The source gate passed under Node 22, including 40 Python tests. Added tests verify
that SQL connection failures cross the runtime boundary as an allowlisted code,
without upstream exception text. Other connector bundles are unchanged.

SQL password authentication is the live-tested mode. Entra modes remain
unqualified. Discovery is limited to selected table columns; source-wide browsing
is not implied. Public catalogue qualification and installed registry CLI checks
follow publication of core 0.12.7 and its matching CLI.

Core 0.12.7 is now published. CLI 0.17.0 built against that exact registry
dependency also passed the public Files 1.2.0/local 0.4.3 ten-table acceptance
across CSV, TSV, JSON, JSONL and Parquet, including failure recovery. The catalogue
qualifies Files 1.2.0, local 0.4.3 and SQL Server 1.2.0 for core 0.12.7.
