/** Installed source-native PostgreSQL temporal contracts; synthetic loopback only. */
import assert from "node:assert/strict";
import {
  readFileSync,
  writeFileSync,
  readdirSync,
  realpathSync,
} from "node:fs";
import { join, resolve, dirname } from "node:path";
import { spawnSync, execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
const argv = process.argv.slice(2);
assert.equal(argv.length % 2, 0);
const options = Object.fromEntries(
  argv.reduce((a, v, i) => (i % 2 ? a : [...a, [v.slice(2), argv[i + 1]]]), []),
);
for (const key of [
  "fixture",
  "python",
  "core-archive",
  "cli-archive",
  "proof",
  "phase",
])
  assert.ok(options[key]);
const seed = JSON.parse(readFileSync(resolve(options.fixture), "utf8"));
assert.equal(seed.status, "passed");
const root = seed.project,
  cli = realpathSync(seed.cli),
  cliRoot = resolve(dirname(cli), "../../..");
const require = createRequire(join(cliRoot, "package.json")),
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
assert.equal(project.connections.files.settings.connection.host, "127.0.0.1");
const authority = ["--allow-write", "--allow-execute"],
  selection = {
    connection: "files",
    executor: seed.provider,
    envFile: ".private.env",
  },
  source = { schema: "public", table: "orders" };
function operation(name, input, permissions = authority) {
  const child = spawnSync(
    process.execPath,
    [
      cli,
      "--project",
      root,
      "--json",
      "--no-input",
      "operation",
      name,
      ...permissions,
    ],
    {
      cwd: root,
      input: JSON.stringify(input),
      encoding: "utf8",
      timeout: 180000,
    },
  );
  assert.equal(child.error, undefined);
  return JSON.parse(child.stdout);
}
function passed(value) {
  assert.equal(value.ok, true, JSON.stringify(value));
  return value.result;
}
const walk = (path) =>
  readdirSync(path, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory()
      ? walk(join(path, entry.name))
      : [join(path, entry.name)],
  );
const run = (args) =>
  operation("run", {
    ...(args.retry ? {} : { flow: "temporal_database" }),
    envFile: ".private.env",
    ...args,
  });
let proof;
if (options.phase === "initial") {
  const checks = [];
  const metadata = passed(
    operation("connection_metadata", { ...selection, tables: [source] }),
  );
  const fields = Object.fromEntries(
    metadata.tables[0].columns.map((c) => [c.name, c]),
  );
  assert.equal(fields.day.type, "date");
  assert.equal(fields.event.type, "timestamp");
  assert.equal(fields.zoned.type, "string");
  assert.equal(fields.payload.supported, false);
  assert.equal(fields.id.key, true);
  assert.equal(fields.event.sourceType, "timestamp without time zone(6)");
  assert.doesNotMatch(
    JSON.stringify(metadata),
    /business-preview-only|"rows"|Synthetic-Pass/,
  );
  const sdk = passed(
    await executeAsync(
      { root, allowWrite: true, allowExecute: true },
      "connection_metadata",
      { ...selection, tables: [source] },
    ),
  );
  assert.deepEqual(sdk.tables, metadata.tables);
  const server = createServer(root, true, "dev", false, true),
    client = new Client({ name: "database-temporal", version: "1.0.0" }),
    [a, b] = InMemoryTransport.createLinkedPair();
  await server.connect(a);
  await client.connect(b);
  try {
    const answer = JSON.parse(
      (
        await client.callTool({
          name: "ingestron_connection_metadata",
          arguments: { ...selection, tables: [source] },
        })
      ).content[0].text,
    );
    assert.deepEqual(passed(answer).tables, metadata.tables);
  } finally {
    await client.close();
    await server.close();
  }
  checks.push(
    "Immutable installed PostgreSQL metadata agrees across SDK, CLI and MCP on calendar dates, unzoned microsecond timestamps, nullable fields, source keys and unsupported JSON without reading records",
  );
  const sample = passed(
    operation("connection_sample", {
      ...selection,
      source,
      columns: ["day", "event"],
      limit: 2,
    }),
  );
  assert.deepEqual(sample.sample.rows, [
    ["2024-02-29", "2024-02-29T01:02:03.123456"],
    ["2024-03-01", null],
  ]);
  assert.equal(sample.sample.truncated, true);
  assert.equal(
    operation(
      "connection_sample",
      { ...selection, source, columns: ["day"], limit: 2 },
      ["--allow-write"],
    ).ok,
    false,
  );
  checks.push(
    "Installed bounded date/timestamp samples preserve calendars, all six fractional digits and nulls, with source execution denial",
  );
  const drafts = passed(
    operation("connection_drafts", {
      ...selection,
      tables: [{ source, name: "dates" }],
    }),
  );
  assert.equal(drafts.tables.length, 1);
  const table = drafts.tables[0],
    document = parse(readFileSync(join(root, table.file), "utf8")),
    properties = document.schema[0].properties;
  assert.equal(properties.find((f) => f.name === "day").physicalType, "DATE");
  assert.equal(
    properties.find((f) => f.name === "event").physicalType,
    "TIMESTAMP",
  );
  assert.ok(!properties.some((f) => f.name === "payload"));
  assert.ok(table.skipped.some((f) => f.name === "payload"));
  properties.splice(
    properties.findIndex((f) => f.name === "zoned"),
    1,
  ); // This journey reviews the unzoned scope explicitly.
  properties.find((f) => f.name === "day").quality = [
    {
      id: "dates-day-valid",
      metric: "invalidValues",
      arguments: { validValues: ["2024-02-29", "2024-03-01"] },
      mustBe: 0,
      severity: "error",
    },
  ];
  const event = properties.find((f) => f.name === "event");
  event.physicalName = "event";
  event.name = "event_time";
  writeFileSync(join(root, table.file), stringify(document));
  const native = passed(
    operation("contract_check", { id: table.file, native: true }, []),
  ).columns;
  assert.equal(native.find((f) => f.name === "day").type, "DATE");
  assert.equal(native.find((f) => f.name === "event").type, "TIMESTAMP");
  checks.push(
    "Source-native discovery produces reviewed DATE/TIMESTAMP contracts with no text inference; unsupported fields remain explained and typed quality is explicit",
  );
  const proposal = passed(
    operation(
      "connection_flow_review",
      {
        connection: selection.connection,
        executor: selection.executor,
        id: "temporal_database",
        provider: "local",
        runtime: seed.provider,
        receipt: drafts.receipt,
        tables: [{ id: table.id, table: table.name, contract: table.file }],
      },
      ["--allow-write"],
    ),
  );
  passed(operation("apply", { proposal }, ["--allow-write"]));
  passed(
    operation("connection_prepare", { flow: "temporal_database" }, [
      "--allow-write",
    ]),
  );
  passed(operation("validate", {}));
  passed(operation("build", {}));
  passed(
    operation(
      "runtime_prepare",
      { flow: "temporal_database", python: options.python },
      [...authority, "--allow-network"],
    ),
  );
  for (const action of ["discover", "review", "approve"])
    passed(run({ action }));
  const result = passed(run({ runId: "database-temporal-initial" }));
  assert.equal(result.result.flows[0].tables[0].rows, 3);
  const outputs = walk(join(root, "build/generated/data")).filter(
    (path) =>
      path.includes("/database-temporal-initial/") && path.endsWith(".parquet"),
  );
  assert.equal(outputs.length, 1);
  const python = readdirSync(join(root, ".ingestron/runtimes"))
    .filter((k) => /^[a-f0-9]{64}$/.test(k))
    .map((k) => join(root, ".ingestron/runtimes", k, "bin/python"))[0];
  assert.ok(python);
  execFileSync(python, [
    "-c",
    `import sys
from datetime import date,datetime
import pyarrow as pa
import pyarrow.parquet as pq
t=pq.read_table(sys.argv[1])
assert t.schema.field('day').type==pa.date32()
assert t.schema.field('event_time').type==pa.timestamp('us')
rows=sorted(t.to_pylist(),key=lambda r:r['id'])
assert rows[0]['day']==date(2024,2,29)
assert rows[0]['event_time']==datetime(2024,2,29,1,2,3,123456)
assert rows[1]['event_time'] is None
`,
    outputs[0],
  ]);
  checks.push(
    "Reviewed installed local-provider execution reads the real driver and publishes native date32, mapped microsecond TIMESTAMP and nulls after typed quality",
  );
  const git = (dir) =>
    execFileSync("git", ["rev-parse", "HEAD"], {
      cwd: join(root, dir),
      encoding: "utf8",
    }).trim();
  const archive = (path) => ({
    path: resolve(path),
    sha256: createHash("sha256")
      .update(readFileSync(resolve(path)))
      .digest("hex"),
  });
  proof = {
    apiVersion: "ingestron.database-temporal-acceptance/v1",
    result: "initial_passed",
    root,
    cli: seed.cli,
    sourceRef: seed.source,
    providerRef: seed.provider,
    sourceCommit: git("source"),
    providerCommit: git("provider"),
    archives: {
      core: archive(options["core-archive"]),
      cli: archive(options["cli-archive"]),
    },
    contracts: drafts.tables,
    checks,
    limits: [
      "Disposable loopback PostgreSQL only; other database transports and native targets require separate qualification",
      "Timezone and greater-than-microsecond mappings remain unimplemented",
      "No live accounts, external source access or public release",
    ],
  };
} else {
  proof = JSON.parse(readFileSync(resolve(options.proof), "utf8"));
  assert.equal(proof.root, root);
  if (options.phase === "quality-failure") {
    assert.equal(proof.result, "initial_passed");
    const failed = run({ runId: "database-temporal-quality" });
    assert.equal(failed.ok, false);
    assert.equal(failed.diagnostics[0].code, "QUALITY_FAILED");
    assert.doesNotMatch(
      JSON.stringify(failed),
      /business-preview-only|2024-03-02|Synthetic-Pass/,
    );
    assert.ok(
      !walk(join(root, "build/generated/data")).some((path) =>
        path.includes("/database-temporal-quality/"),
      ),
    );
    proof.checks.push(
      "A changed source date fails the reviewed temporal quality rule without record values or partial publication",
    );
    proof.result = "failure_verified";
  } else {
    assert.equal(options.phase, "recovery");
    assert.equal(proof.result, "failure_verified");
    const result = passed(run({ retry: "database-temporal-quality" }));
    assert.equal(result.result.flows[0].tables[0].rows, 3);
    proof.checks.push(
      "Correction of the real source row and same-run retry recover typed output without bypassing review or ownership",
    );
    proof.result = "passed";
  }
}
for (const file of readdirSync(join(root, ".ingestron/source-access")).filter(
  (f) => f.endsWith(".json"),
))
  assert.doesNotMatch(
    readFileSync(join(root, ".ingestron/source-access", file), "utf8"),
    /business-preview-only|"rows"|Synthetic-Pass/,
  );
writeFileSync(resolve(options.proof), JSON.stringify(proof, null, 2) + "\n");
console.log(
  JSON.stringify({ result: proof.result, root, checks: proof.checks.length }),
);
