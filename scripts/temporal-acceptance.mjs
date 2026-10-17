/** Installed reviewed temporal contracts through all five local file formats. */
import assert from "node:assert/strict";
import {
  cpSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
  readdirSync,
  realpathSync,
} from "node:fs";
import { join, resolve, dirname } from "node:path";
import { spawnSync, execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
const argv = process.argv.slice(2);
assert.equal(argv.length % 2, 0);
const options = Object.fromEntries(
  argv.reduce((a, v, i) => (i % 2 ? a : [...a, [v.slice(2), argv[i + 1]]]), []),
);
for (const key of ["fixture", "out", "proof"])
  assert.ok(options[key], "Supply --" + key);
const seed = JSON.parse(readFileSync(resolve(options.fixture), "utf8"));
assert.equal(seed.result, "passed");
mkdirSync(resolve(options.out), { recursive: true });
const root = mkdtempSync(join(resolve(options.out), "temporal-"));
cpSync(seed.root, root, {
  recursive: true,
  filter: (path) => path !== join(seed.root, "build"),
});
const cliRoot = realpathSync(resolve(dirname(seed.cli), "../ingestron")),
  require = createRequire(join(cliRoot, "package.json")),
  { parse, stringify } = require("yaml");
const { executeAsync } = await import(
  pathToFileURL(resolve(cliRoot, "../@ingestron/core/dist/sdk/index.js")).href
);
const { createServer } = await import(
  pathToFileURL(join(cliRoot, "build/cli/mcp/index.js")).href
);
const { Client } = await import(
  pathToFileURL(require.resolve("@modelcontextprotocol/sdk/client/index.js"))
    .href
);
const { InMemoryTransport } = await import(
  pathToFileURL(require.resolve("@modelcontextprotocol/sdk/inMemory.js")).href
);
const project = parse(readFileSync(join(root, "project.yaml"), "utf8"));
project.id = "temporal_installed_acceptance";
project.flows = [];
writeFileSync(join(root, "project.yaml"), stringify(project));
const checks = [],
  selection = { connection: "starter", executor: seed.providerRef },
  authority = ["--allow-write", "--allow-execute"];
function command(args, input) {
  const child = spawnSync(
    seed.cli,
    ["--project", root, "--json", "--no-input", ...args],
    {
      input: input === undefined ? undefined : JSON.stringify(input),
      encoding: "utf8",
      timeout: 180000,
    },
  );
  assert.equal(child.error, undefined);
  return JSON.parse(child.stdout);
}
const operation = (name, input, flags = authority) =>
  command(["operation", name, ...flags], input);
function passed(value) {
  assert.equal(value.ok, true, JSON.stringify(value));
  return value.result;
}
const walk = (folder) =>
  readdirSync(folder, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory()
      ? walk(join(folder, entry.name))
      : [join(folder, entry.name)],
  );
const key = readdirSync(join(root, ".ingestron/runtimes")).find((name) =>
    /^[a-f0-9]{64}$/.test(name),
  ),
  python = join(root, ".ingestron/runtimes", key, "bin/python");
assert.ok(key);
const data = join(root, "data/temporal");
mkdirSync(data);
const records = [
  {
    id: 1,
    day: "2024-02-29",
    event: "2024-02-29T01:02:03.123456",
    label: "PRIVATE_TEMPORAL_RECORD",
  },
  { id: 2, day: "2024-03-01", event: null, label: "second" },
  { id: 3, day: "2024-02-29", event: "2024-02-29T23:59:59", label: "third" },
];
const formats = ["csv", "tsv", "json", "jsonl", "parquet"];
for (const format of formats) {
  const path = join(data, "records." + format);
  if (format === "json") writeFileSync(path, JSON.stringify(records));
  else if (format === "jsonl")
    writeFileSync(
      path,
      records.map((record) => JSON.stringify(record)).join("\n") + "\n",
    );
  else if (format === "parquet")
    execFileSync(python, [
      "-c",
      `import sys
from datetime import date,datetime
import pyarrow as pa
import pyarrow.parquet as pq
pq.write_table(pa.table({'id':[1,2,3],'day':pa.array([date(2024,2,29),date(2024,3,1),date(2024,2,29)],type=pa.date32()),'event':pa.array([datetime(2024,2,29,1,2,3,123456),None,datetime(2024,2,29,23,59,59)],type=pa.timestamp('us')),'label':['PRIVATE_TEMPORAL_RECORD','second','third']}),sys.argv[1])`,
      path,
    ]);
  else {
    const separator = format === "csv" ? "," : "\t";
    writeFileSync(
      path,
      ["id", "day", "event", "label"].join(separator) +
        "\n" +
        records
          .map((record) =>
            [record.id, record.day, record.event ?? "", record.label].join(
              separator,
            ),
          )
          .join("\n") +
        "\n",
    );
  }
}
const sources = formats.map((format) => ({
    path: join(data, "records." + format),
    format,
  })),
  parquet = sources.at(-1),
  request = { ...selection, tables: [parquet] };
const metadata = passed(operation("connection_metadata", request));
assert.deepEqual(
  metadata.tables[0].columns.map((field) => field.type),
  ["integer", "date", "timestamp", "string"],
);
assert.equal(metadata.scope, "metadata");
assert.doesNotMatch(JSON.stringify(metadata), /PRIVATE_TEMPORAL_RECORD|"rows"/);
assert.deepEqual(
  passed(
    await executeAsync(
      { root, allowWrite: true, allowExecute: true },
      "connection_metadata",
      request,
    ),
  ).tables,
  metadata.tables,
);
const server = createServer(root, true, "dev", false, true),
  client = new Client({ name: "temporal-acceptance", version: "1.0.0" }),
  [a, b] = InMemoryTransport.createLinkedPair();
await server.connect(a);
await client.connect(b);
try {
  const result = JSON.parse(
    (
      await client.callTool({
        name: "ingestron_connection_metadata",
        arguments: request,
      })
    ).content[0].text,
  );
  assert.deepEqual(passed(result).tables, metadata.tables);
} finally {
  await client.close();
  await server.close();
}
checks.push(
  "Installed SDK, CLI and MCP agree on record-free native Parquet DATE/TIMESTAMP metadata without string inference",
);
const drafts = passed(
  operation("connection_drafts", {
    ...selection,
    tables: sources.map((source, i) => ({
      source,
      name: "temporal_" + formats[i],
    })),
    options: { sampleRecords: true, limit: 2 },
  }),
);
assert.equal(drafts.tables.length, 5);
for (const table of drafts.tables) {
  const document = parse(readFileSync(join(root, table.file), "utf8")),
    fields = document.schema[0].properties;
  for (const [name, type, logical] of [
    ["id", "BIGINT", "integer"],
    ["day", "DATE", "date"],
    ["event", "TIMESTAMP", "timestamp"],
  ]) {
    const field = fields.find((field) => field.name === name);
    assert.ok(field);
    field.physicalType = type;
    field.logicalType = logical;
    field.required = name !== "event";
    if (name === "id") field.primaryKey = true;
    if (name === "day")
      field.quality = [
        {
          id: table.name + "-day-valid",
          metric: "invalidValues",
          arguments: { validValues: ["2024-02-29", "2024-03-01"] },
          mustBe: 0,
          severity: "error",
        },
      ];
  }
  writeFileSync(join(root, table.file), stringify(document));
  const native = passed(
    operation("contract_check", { id: table.file, native: true }, []),
  ).columns;
  assert.deepEqual(
    ["id", "day", "event"].map(
      (name) => native.find((field) => field.name === name)?.type,
    ),
    ["BIGINT", "DATE", "TIMESTAMP"],
  );
}
checks.push(
  "Five reviewed contracts explicitly select temporal physical types, nullability, keys and typed day-quality rules; text metadata remains STRING until review",
);
const proposal = passed(
  operation(
    "connection_flow_review",
    {
      ...selection,
      id: "temporal_snapshot",
      provider: "local",
      receipt: drafts.receipt,
      tables: drafts.tables.map((table) => ({
        id: table.id,
        table: table.name,
        contract: table.file,
      })),
    },
    ["--allow-write"],
  ),
);
passed(operation("apply", { proposal }, ["--allow-write"]));
passed(
  operation("connection_prepare", { flow: "temporal_snapshot" }, [
    "--allow-write",
  ]),
);
for (const cmd of [
  ["check"],
  ["build"],
  ["runtime", "prepare"],
  ["run", "--action", "discover"],
  ["run", "--action", "review"],
  ["run", "--action", "approve"],
])
  passed(command(cmd));
const run = passed(command(["run", "--run-id", "temporal-initial"]));
assert.deepEqual(
  Object.fromEntries(
    run.result.flows[0].tables.map((table) => [table.stream, table.rows]),
  ),
  Object.fromEntries(formats.map((format) => ["temporal_" + format, 3])),
);
const outputs = walk(join(root, "build/generated/data")).filter(
  (path) => path.includes("/temporal-initial/") && path.endsWith(".parquet"),
);
assert.equal(outputs.length, 5);
execFileSync(python, [
  "-c",
  `import sys
from datetime import date,datetime
import pyarrow as pa
import pyarrow.parquet as pq
for path in sys.argv[1:]:
 table=pq.read_table(path)
 assert table.schema.field('day').type==pa.date32()
 assert table.schema.field('event').type==pa.timestamp('us')
 rows=table.to_pylist()
 assert rows[0]['day']==date(2024,2,29)
 assert rows[0]['event']==datetime(2024,2,29,1,2,3,123456)
 assert rows[1]['event'] is None
`,
  ...outputs,
]);
checks.push(
  "Installed core/local-provider execution publishes all five formats as native date32 and exact microsecond timestamp Parquet after reviewed quality gates",
);
const last = join(data, "records.jsonl"),
  original = readFileSync(last, "utf8");
try {
  writeFileSync(last, original.replace("2024-03-01", "2024-03-02"));
  const failed = command(["run", "--run-id", "temporal-quality"]);
  assert.equal(failed.ok, false);
  assert.equal(failed.diagnostics[0].code, "QUALITY_FAILED");
  assert.ok(
    !walk(join(root, "build/generated/data")).some((path) =>
      path.includes("/temporal-quality/"),
    ),
  );
  writeFileSync(last, original);
  passed(command(["run", "--retry", "temporal-quality"]));
} finally {
  writeFileSync(last, original);
}
checks.push(
  "A valid but disallowed calendar day fails typed quality before any table publication; correction and same-run retry recover all five tables",
);
try {
  writeFileSync(last, original.replace(".123456", ".1234567"));
  const failed = command(["run", "--run-id", "temporal-precision"]);
  assert.equal(failed.ok, false);
  assert.match(
    JSON.stringify(failed.diagnostics),
    /six fractional digits.*precision mapping/,
  );
  assert.doesNotMatch(
    JSON.stringify(failed),
    /PRIVATE_TEMPORAL_RECORD|1234567/,
  );
  assert.ok(
    !walk(join(root, "build/generated/data")).some((path) =>
      path.includes("/temporal-precision/"),
    ),
  );
  writeFileSync(last, original);
  passed(command(["run", "--retry", "temporal-precision"]));
} finally {
  writeFileSync(last, original);
}
checks.push(
  "Overprecision is refused without rounding, business diagnostics or partial publication; corrected input recovers the same run",
);
for (const [runId, before, after, guidance] of [
  [
    "temporal-calendar",
    "2024-03-01",
    "2023-02-29",
    /valid calendar date.*YYYY-MM-DD/,
  ],
  [
    "temporal-timezone",
    ".123456",
    ".123456+13:00",
    /timezone-less.*timezone mapping/,
  ],
]) {
  try {
    writeFileSync(last, original.replace(before, after));
    const failed = command(["run", "--run-id", runId]);
    assert.equal(failed.ok, false);
    assert.match(JSON.stringify(failed.diagnostics), guidance);
    assert.doesNotMatch(
      JSON.stringify(failed),
      /PRIVATE_TEMPORAL_RECORD|2023-02-29|\+13:00/,
    );
    assert.ok(
      !walk(join(root, "build/generated/data")).some((path) =>
        path.includes("/" + runId + "/"),
      ),
    );
    writeFileSync(last, original);
    passed(command(["run", "--retry", runId]));
  } finally {
    writeFileSync(last, original);
  }
}
checks.push(
  "Invalid calendar and timezone values provide fixed actionable guidance without source values or partial output, then recover by corrected same-run retries",
);
for (const path of readdirSync(join(root, ".ingestron/source-access")).filter(
  (name) => name.endsWith(".json"),
))
  assert.doesNotMatch(
    readFileSync(join(root, ".ingestron/source-access", path), "utf8"),
    /PRIVATE_TEMPORAL_RECORD|"rows"/,
  );
checks.push(
  "Metadata/draft receipts retain types and sample counts without business record values",
);
writeFileSync(
  resolve(options.proof),
  JSON.stringify(
    {
      apiVersion: "ingestron.temporal-acceptance/v1",
      result: "passed",
      root,
      cli: seed.cli,
      sourceRef: seed.sourceRef,
      providerRef: seed.providerRef,
      sourceCommit: seed.sourceCommit,
      providerCommit: seed.providerCommit,
      archives: seed.archives,
      contracts: drafts.tables,
      checks,
      limits: [
        "Synthetic local source/project only; no accounts or external vendor access",
        "TIMESTAMP is timezone-less at microsecond precision; offsets/nanoseconds require explicit future mapping",
        "Database/API/native target qualification and authenticated browser remain separate",
      ],
    },
    null,
    2,
  ) + "\n",
);
console.log(JSON.stringify({ result: "passed", checks: checks.length, root }));
