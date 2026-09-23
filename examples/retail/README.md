# Read the retail files

This fictional NZ retailer has three customers, three products and three orders.
Read the three tables into separate Parquet snapshots, then verify an order value
of NZD 61.95. The inspection script calculates that check locally; the connector
itself does not join or transform tables.

Use CLI 0.15.0 with core 0.12.2 and local provider 0.4.1, Git, Python 3.12
and the files connector. No cloud account or credential is needed. Follow the
[installation guide](https://docs.ingestron.io/docs/start/installation) for Python
preparation. First preparation downloads locked dependencies.

In a fresh copy of this directory:

```sh
python3 setup.py
ingestron provider install local@0.4.1
ingestron connector install files@1.0.1
ingestron check
ingestron build
ingestron runtime prepare
ingestron run --action discover
ingestron run --action review
```

Open `project.yaml` and each `build/generated/flows/*/review.json`. Confirm the
input paths, selected columns, required fields and `DECIMAL(10,2)` price. Approve
only after checking those choices:

```sh
ingestron run --action approve
ingestron run --run-id retail-001
python3 inspect-output.py
ingestron run --retry retail-001
```

Expect three rows in each output, quantity 7 and value NZD 61.95. The checks also
verify an embedded newline and a null email. Output is under
`build/generated/data/<flow>/<identity-hash>/retail-001/records.parquet`.
Each flow commits independently; the three-table run is not one transaction.

To compare formats, make a fresh copy and run `python3 setup.py --format parquet`
(or `tsv`, `json`, `jsonl`). Follow the same steps. Do not overwrite an existing
project or approved review. Setup deliberately refuses an existing project.

For a rejection exercise, after a successful run change a numeric input to invalid
text and use a new run ID. Expect failure without committed output for that flow.
The successful snapshot remains intact. Restore the original file to recover.
To add a column, use a separate copy, edit the contract and source, then build,
discover, review and approve again. New data is not automatically approved.

`data/` contains only fictional fixtures, published under the accompanying
Apache-2.0 licence by Otrera Limited. `provenance.json` pins their bytes to the
canonical private demo source revision. No infrastructure, endpoints or credentials
are included. Keep any output you need before deleting your disposable copy.
