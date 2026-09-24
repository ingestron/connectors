# Read the retail files

This fictional NZ retailer has three customers, three products and three orders.
The current project uses Files 1.1.0: one local-files connection serves three
tables in one ingestion flow. Each table names its file and has a separate ODCS
data contract. The output is three Parquet snapshots, with an order value of
NZD 61.95. The inspection script calculates that value; the connector does not
join or transform the tables.

Follow the [manual retail tutorial](https://docs.ingestron.io/docs/tutorials/retail-files)
to write the project and contracts yourself. The files here are a completed
example you can compare with your work. Use CLI 0.15.1, local provider 0.4.1,
Git and Python 3.12 on macOS or Linux. No cloud account or credential is needed.

For a quick run in a fresh copy of this directory:

```sh
python3 setup.py
ingestron provider install local@0.4.1
ingestron connector install files@1.1.0
ingestron check
ingestron build
ingestron runtime prepare
ingestron run --action discover
ingestron run --action review
```

Setup verifies the hashes of the fictional data and fills absolute paths in
`project.yaml`; it refuses to replace an existing project. Open the project,
the three files under `contracts/` and the review under
`build/generated/flows/retail_local/review.json`. Check the selected paths,
columns, required fields and `DECIMAL(10,2)` price before approving:

```sh
ingestron run --action approve
ingestron run --run-id retail-001
python3 inspect-output.py
ingestron run --retry retail-001
```

Expect three rows in each output, quantity 7 and value NZD 61.95. The check
also verifies a null email and an embedded newline. The three Parquet files
share one commit under `build/generated/data/retail_local/<identity-hash>/retail-001/`.
To compare formats, use a fresh copy and run `python3 setup.py --format parquet`
(or `tsv`, `json`, `jsonl`). Do not overwrite an approved review with a different
source selection.

For a rejection exercise, change a numeric value in a copied CSV input to
invalid text and use a new run ID. Expect no committed output for that run.
Restore the file and retry the failed run. A changed path, format or contract
requires a new build, discovery and review; installation never changes the
project for you.

`data/` contains only fictional fixtures, published under the accompanying
Apache-2.0 licence by Otrera Limited. `provenance.json` pins their bytes to
the original demo-source revision. No infrastructure, endpoints or credentials
are included. The [Files 1.0.1 retail download](https://github.com/ingestron/connectors/releases/tag/files-1.0.1)
remains available with its original three-connection layout.
