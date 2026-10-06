/** Immutable installed Files inventory, sample and snapshot journey; local synthetic files only. */
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import {
  cpSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
  realpathSync,
  readdirSync,
} from "node:fs";
import { resolve, dirname, join } from "node:path";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
const args = process.argv.slice(2);
assert.equal(args.length % 2, 0);
const options = Object.fromEntries(
  args.reduce(
    (pairs, v, i, a) =>
      i % 2 === 0 ? [...pairs, [v.slice(2), a[i + 1]]] : pairs,
    [],
  ),
);
for (const name of [
  "cli",
  "core-archive",
  "cli-archive",
  "connectors",
  "provider",
  "cache",
  "out",
  "proof",
])
  assert.ok(options[name], "Supply --" + name);
const cli = resolve(options.cli),
  cliRoot = realpathSync(resolve(dirname(cli), "../ingestron")),
  coreRoot = realpathSync(resolve(cliRoot, "../@ingestron/core"));
const require = createRequire(resolve(cliRoot, "package.json"));
const { stringify } = require("yaml");
const { executeAsync } = await import(
  pathToFileURL(resolve(coreRoot, "dist/sdk/index.js")).href
);
const { createServer } = await import(
  pathToFileURL(resolve(cliRoot, "build/cli/mcp/index.js")).href
);
const { Client } = await import(
  pathToFileURL(require.resolve("@modelcontextprotocol/sdk/client/index.js"))
    .href
);
const { InMemoryTransport } = await import(
  pathToFileURL(require.resolve("@modelcontextprotocol/sdk/inMemory.js")).href
);
mkdirSync(options.out, { recursive: true });
const base = mkdtempSync(join(resolve(options.out), "files-schema-"));
const root = join(base, "project");
mkdirSync(root);
cpSync(
  resolve(options.connectors, "connectors/files"),
  join(root, "source/connectors/files"),
  { recursive: true },
);
cpSync(resolve(options.provider, "plugin"), join(root, "provider/plugin"), {
  recursive: true,
});
const version = require("yaml").parse(
  readFileSync(join(root, "source/connectors/files/connector.yaml"), "utf8"),
).version;
const parse = require("yaml").parse;
const providerVersion = parse(
  readFileSync(join(root, "provider/plugin/provider.yaml"), "utf8"),
).version;
const git = (directory, ...args) =>
  execFileSync("git", args, {
    cwd: directory,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
for (const [directory, tag] of [
  [join(root, "source"), version],
  [join(root, "provider"), providerVersion],
]) {
  git(directory, "init", "-q");
  git(directory, "add", ".");
  git(
    directory,
    "-c",
    "user.name=Synthetic acceptance",
    "-c",
    "user.email=acceptance@example.invalid",
    "commit",
    "-qm",
    "Immutable Files schema acceptance",
  );
  git(directory, "tag", tag);
}
const sourceRef = "example/files/connectors/files/connector.yaml@" + version,
  providerRef = "example/local/plugin/provider.yaml@" + providerVersion;
const data = join(root, "data");
mkdirSync(data);
const first =
  "id,label\n9007199254740993,files-private-preview\n2,second\n3,third\n";
const second = "id\tlabel\n1\tsecond-table\n";
writeFileSync(join(data, "first.csv"), first);
writeFileSync(join(data, "second.tsv"), second);
const contract = (name) => ({
  apiVersion: "v3.1.0",
  kind: "DataContract",
  id: "files-" + name,
  name: "Synthetic " + name,
  version: "1.0.0",
  status: "draft",
  schema: [
    {
      name,
      logicalType: "object",
      physicalType: "table",
      properties: [
        {
          name: "id",
          logicalType: "integer",
          physicalType: "BIGINT",
          required: true,
          primaryKey: true,
        },
        {
          name: "label",
          logicalType: "string",
          physicalType: "STRING",
          required: true,
        },
      ],
    },
  ],
});
const project = {
  apiVersion: "ingestron.project/v1",
  id: "files_inventory_acceptance",
  packages: { starter: sourceRef, local: providerRef },
  providers: {
    configurations: { local: { package: "local", binding: "runtime" } },
  },
  defaults: { provider: "local" },
  environments: {
    dev: {
      apiVersion: "ingestron.environment/v1",
      environment: "dev",
      bindings: { runtime: { kind: "local" } },
    },
  },
  connections: {
    starter: {
      package: "starter",
      sourceId: "synthetic",
      tenantId: "training",
      settings: {},
    },
  },
  flows: [],
};
writeFileSync(join(root, "project.yaml"), stringify(project));
const permissions = ["--allow-write", "--allow-execute"];
function command(...args) {
  const r = spawnSync(
    cli,
    ["--project", root, "--json", "--no-input", ...args],
    { encoding: "utf8", timeout: 120000 },
  );
  assert.equal(r.error, undefined);
  return JSON.parse(r.stdout);
}
function operation(name, args = {}, permissions = []) {
  const r = spawnSync(
    cli,
    [
      "--project",
      root,
      "--json",
      "--no-input",
      "operation",
      name,
      ...permissions,
    ],
    { input: JSON.stringify(args), encoding: "utf8", timeout: 120000 },
  );
  assert.equal(r.error, undefined);
  return JSON.parse(r.stdout);
}
const passed = (r) => {
  assert.equal(r.ok, true, JSON.stringify(r));
  return r.result;
};
for (const [reference, fromGit] of [
  [sourceRef, "source"],
  [providerRef, "provider"],
])
  passed(
    operation("packages_install", { reference, fromGit }, ["--allow-write"]),
  );
const sourceCommit = git(join(root, "source"), "rev-parse", "HEAD").trim(),
  providerCommit = git(join(root, "provider"), "rev-parse", "HEAD").trim();
const checks = [
  "Files package installs and locks an immutable source/runtime and provider snapshot through the installed CLI/core",
];
const cache = join(root, ".ingestron/runtime-cache");
cpSync(realpathSync(options.cache), cache, { recursive: true });
if (options.fresh !== "true")
  cpSync(realpathSync(options.cache), join(root, ".ingestron/runtimes"), {
    recursive: true,
  });
const rawAssets = JSON.parse(
  readFileSync(join(root, "source/connectors/files/runtime.json"), "utf8"),
);
const platform = execFileSync(
  options.python ?? "python3.12",
  ["-c", "import platform; print(platform.platform()+platform.machine())"],
  { encoding: "utf8" },
).trim();
const key = createHash("sha256")
  .update(
    Buffer.concat([
      Buffer.from(rawAssets["requirements.lock.txt"]),
      Buffer.from([0]),
      Buffer.from(rawAssets["build-tools.lock.txt"]),
      Buffer.from(platform),
    ]),
  )
  .digest("hex");
if (options.fresh !== "true")
  assert.equal(
    JSON.parse(readFileSync(join(cache, key, "ready.json"), "utf8")).lock,
    key,
    "Qualified dependency cache required before cached preparation",
  );
const selection = { connection: "starter", executor: providerRef };
const scope = { directory: data };
const prepared = passed(
  operation("connection_runtime_prepare", selection, [
    ...permissions,
    "--allow-network",
  ]),
);
assert.equal(prepared.reused, options.fresh !== "true");

const schemaOptions = { sampleRecords: true, limit: 2 };
const jsonFile = join(data, "records.json"),
  jsonlFile = join(data, "records.jsonl");
const jsonText =
  '[{"id":9223372036854775807,"amount":12.30,"label":"PRIVATE_SCHEMA_RECORD","active":true},{"id":2,"amount":0.01,"label":"second","active":false},{"id":3,"amount":9.99,"label":"third","active":true}]';
const jsonlText =
  '{"id":1,"amount":1.20,"label":"PRIVATE_SCHEMA_JSONL","active":true}\n{"id":2,"amount":2.30,"label":"next","active":false}\n';
writeFileSync(jsonFile, jsonText);
writeFileSync(jsonlFile, jsonlText);
const tables = [
  { path: jsonFile, format: "json" },
  { path: jsonlFile, format: "jsonl" },
];
const request = { ...selection, tables, options: schemaOptions };
const info = passed(operation("connection_access", selection));
assert.equal(info.metadataOptionsSchema.properties.limit.maximum, 50);
const beforeReceipts = readdirSync(join(root, ".ingestron/source-access"));
for (const invalid of [
  { sampleRecords: false },
  { sampleRecords: true, limit: 51 },
  { sampleRecords: true, private: "PRIVATE_OPTIONS" },
]) {
  const result = operation(
    "connection_metadata",
    { ...request, options: invalid },
    permissions,
  );
  assert.equal(result.ok, false);
  assert.equal(result.diagnostics[0].code, "CONNECTION");
  assert.doesNotMatch(JSON.stringify(result), /PRIVATE_OPTIONS/);
}
assert.deepEqual(
  readdirSync(join(root, ".ingestron/source-access")),
  beforeReceipts,
);
assert.equal(
  operation("connection_metadata", request, ["--allow-write"]).ok,
  false,
);
const recordFree = operation(
  "connection_metadata",
  { ...selection, tables },
  permissions,
);
assert.equal(recordFree.ok, false);
assert.equal(recordFree.diagnostics[0].code, "CAPABILITY");
checks.push(
  "Installed source-owned options require explicit valid sampling consent and execution; default JSON metadata remains record-free and unsupported",
);
const metadata = passed(operation("connection_metadata", request, permissions));
const terminal = passed(
  command(
    "connection",
    "metadata",
    "starter",
    "--executor",
    providerRef,
    "--tables",
    JSON.stringify(tables),
    "--options",
    JSON.stringify(schemaOptions),
  ),
);
const sdk = passed(
  await executeAsync(
    { root, allowWrite: true, allowExecute: true },
    "connection_metadata",
    request,
  ),
);
assert.deepEqual(terminal.tables, metadata.tables);
assert.deepEqual(sdk.tables, metadata.tables);
assert.equal(metadata.scope, "data");
assert.equal(metadata.tables[0].sampling.truncated, true);
assert.equal(metadata.tables[1].sampling.truncated, false);
for (const table of metadata.tables) {
  assert.equal(table.sampling.rowCount, 2);
  assert.ok(table.columns.every((c) => c.nullable && !c.key));
  assert.equal(table.columns.find((c) => c.name === "id").type, "integer");
  assert.deepEqual(
    table.columns.find((c) => c.name === "amount"),
    {
      name: "amount",
      type: "decimal",
      nullable: true,
      precision: 38,
      scale: 2,
    },
  );
}
assert.doesNotMatch(
  JSON.stringify(metadata),
  /PRIVATE_SCHEMA_RECORD|PRIVATE_SCHEMA_JSONL|"rows"/,
);
checks.push(
  "Installed SDK, CLI operation and terminal metadata command return identical int64 and decimal suggestions with sample bounds and no record payload",
);
const parquetFile = join(data, "records.parquet");
execFileSync(
  join(root, ".ingestron/runtimes", key, "bin/python"),
  [
    "-c",
    `import sys
from decimal import Decimal
import pyarrow as pa
import pyarrow.parquet as pq
table=pa.table({'id':pa.array([9223372036854775807,2,3],type=pa.int64()),'amount':pa.array([Decimal('12.30'),Decimal('0.01'),Decimal('9.99')],type=pa.decimal128(20,2)),'label':['PRIVATE_PARQUET_PREVIEW','second','third']})
pq.write_table(table,sys.argv[1],compression='NONE',row_group_size=2)
`,
    parquetFile,
  ],
  { encoding: "utf8" },
);
const formatSources = [
  { path: join(data, "first.csv"), format: "csv" },
  { path: join(data, "second.tsv"), format: "tsv" },
  { path: parquetFile, format: "parquet" },
];
const formatMetadata = passed(
  operation(
    "connection_metadata",
    { ...selection, tables: formatSources },
    permissions,
  ),
);
assert.equal(formatMetadata.scope, "metadata");
assert.equal(formatMetadata.tables.length, 3);
assert.deepEqual(
  formatMetadata.tables[2].columns.find((column) => column.name === "amount"),
  { name: "amount", type: "decimal", nullable: true, precision: 20, scale: 2 },
);
assert.doesNotMatch(
  JSON.stringify(formatMetadata),
  /PRIVATE_PARQUET_PREVIEW|files-private-preview|"rows"/,
);
for (const source of formatSources) {
  const columns =
    source.format === "parquet" ? ["amount", "id"] : ["label", "id"];
  const request = { ...selection, source, columns, limit: 1 };
  const preview = passed(operation("connection_sample", request, permissions));
  assert.equal(preview.sample.rows.length, 1);
  assert.deepEqual(preview.sample.columns, columns);
  assert.deepEqual(
    passed(
      await executeAsync(
        { root, allowWrite: true, allowExecute: true },
        "connection_sample",
        request,
      ),
    ).sample,
    preview.sample,
  );
  assert.deepEqual(
    passed(
      command(
        "connection",
        "sample",
        "starter",
        "--executor",
        providerRef,
        "--source",
        JSON.stringify(source),
        "--columns",
        JSON.stringify(columns),
        "--limit",
        "1",
      ),
    ).sample,
    preview.sample,
  );
  if (source.format === "parquet")
    assert.deepEqual(preview.sample.rows, [["12.30", "9223372036854775807"]]);
  if (source.format === "csv")
    assert.deepEqual(preview.sample.rows, [
      ["files-private-preview", "9007199254740993"],
    ]);
}
const headerOnlyFile = join(data, "header-only-metadata.csv");
writeFileSync(headerOnlyFile, "id,label\nPRIVATE_BROKEN_FORMAT_ROW\n");
const headerSource = { path: headerOnlyFile, format: "csv" };
assert.equal(
  passed(
    operation(
      "connection_metadata",
      { ...selection, tables: [headerSource] },
      permissions,
    ),
  ).tables[0].columns.length,
  2,
);
const brokenSample = operation(
  "connection_sample",
  { ...selection, source: headerSource, limit: 1 },
  permissions,
);
assert.equal(brokenSample.ok, false);
assert.doesNotMatch(JSON.stringify(brokenSample), /PRIVATE_BROKEN_FORMAT_ROW/);
const badParquet = join(data, "broken.parquet");
writeFileSync(badParquet, "PRIVATE_BROKEN_PARQUET");
const failedFormats = operation(
  "connection_metadata",
  {
    ...selection,
    tables: [formatSources[0], { path: badParquet, format: "parquet" }],
  },
  permissions,
);
assert.equal(failedFormats.ok, false);
assert.doesNotMatch(JSON.stringify(failedFormats), /PRIVATE_BROKEN_PARQUET/);
checks.push(
  "Installed SDK, CLI operation and terminal agree on CSV/TSV/Parquet bounded ordered previews; metadata keeps exact Parquet decimal schema, reads no malformed CSV business row and rejects a malformed final file atomically",
);
for (const allow of [false, true]) {
  const server = createServer(root, allow, "dev", false, allow),
    client = new Client({ name: "schema-acceptance", version: "1.0.0" }),
    [a, b] = InMemoryTransport.createLinkedPair();
  await server.connect(a);
  await client.connect(b);
  try {
    const advertised = await client.listTools();
    const tool = advertised.tools.find(
      (t) => t.name === "ingestron_connection_metadata",
    );
    assert.equal(!!tool, allow);
    if (allow) {
      assert.ok(tool.inputSchema.properties.options);
      const value = JSON.parse(
        (await client.callTool({ name: tool.name, arguments: request }))
          .content[0].text,
      );
      assert.deepEqual(passed(value).tables, metadata.tables);
      const sampleTool = advertised.tools.find(
        (tool) => tool.name === "ingestron_connection_sample",
      );
      assert.ok(sampleTool);
      const response = JSON.parse(
        (
          await client.callTool({
            name: sampleTool.name,
            arguments: {
              ...selection,
              source: formatSources[2],
              columns: ["amount", "id"],
              limit: 1,
            },
          })
        ).content[0].text,
      );
      assert.deepEqual(passed(response).sample, {
        columns: ["amount", "id"],
        rows: [["12.30", "9223372036854775807"]],
        truncated: true,
      });
    }
  } finally {
    await client.close();
    await server.close();
  }
}
checks.push(
  "Installed MCP advertises generic metadata options only with private-write and source-execution authority and agrees with the other clients",
);
const largeJson = join(data, "large-prefix.json"),
  largeJsonl = join(data, "large-prefix.jsonl");
const largePrefix =
  '{"id":9223372036854775807,"amount":12.340,"label":"PRIVATE_PREFIX_PREVIEW"}';
for (const [file, format, text] of [
  [
    largeJson,
    "json",
    "[" +
      largePrefix +
      "," +
      largePrefix +
      "," +
      largePrefix +
      "," +
      "PRIVATE_UNREAD_SUFFIX".repeat(100000),
  ],
  [
    largeJsonl,
    "jsonl",
    (largePrefix + "\n").repeat(3) + "PRIVATE_UNREAD_SUFFIX".repeat(100000),
  ],
]) {
  writeFileSync(file, text);
  assert.ok(Buffer.byteLength(text) > 1048576);
  const sampleRequest = {
    ...selection,
    source: { path: file, format },
    limit: 2,
    columns: ["amount", "id"],
  };
  const preview = passed(
    operation("connection_sample", sampleRequest, permissions),
  );
  assert.deepEqual(preview.sample, {
    columns: ["amount", "id"],
    rows: [
      ["12.340", "9223372036854775807"],
      ["12.340", "9223372036854775807"],
    ],
    truncated: true,
  });
  assert.deepEqual(
    passed(
      await executeAsync(
        { root, allowWrite: true, allowExecute: true },
        "connection_sample",
        sampleRequest,
      ),
    ).sample,
    preview.sample,
  );
  const terminalSample = passed(
    command(
      "connection",
      "sample",
      "starter",
      "--executor",
      providerRef,
      "--source",
      JSON.stringify(sampleRequest.source),
      "--limit",
      "2",
      "--columns",
      JSON.stringify(sampleRequest.columns),
    ),
  );
  assert.deepEqual(terminalSample.sample, preview.sample);
  assert.doesNotMatch(JSON.stringify(preview), /PRIVATE_UNREAD_SUFFIX/);
  assert.equal(
    operation("connection_sample", sampleRequest, ["--allow-write"]).ok,
    false,
  );
}
checks.push(
  "Installed SDK, CLI operation and terminal sample large JSON/JSONL prefixes with exact int64 and decimal values, ordered selected columns, and source-read permission denial",
);
const badPreviewFile = join(data, "bad-preview.jsonl");
for (const text of [
  largePrefix + "\nPRIVATE_MALFORMED_PREFIX",
  '{"id":"' + "x".repeat(1048576) + '"}\n',
]) {
  writeFileSync(badPreviewFile, text);
  const failed = operation(
    "connection_sample",
    {
      ...selection,
      source: { path: badPreviewFile, format: "jsonl" },
      limit: 2,
    },
    permissions,
  );
  assert.equal(failed.ok, false);
  assert.equal(failed.diagnostics[0].code, "SOURCE_ACCESS");
  assert.doesNotMatch(
    JSON.stringify(failed),
    /PRIVATE_MALFORMED_PREFIX|PRIVATE_PREFIX_PREVIEW|"rows"/,
  );
}
const scalarOnly = passed(
  operation(
    "connection_sample",
    {
      ...selection,
      source: { path: ambiguousPreviewPath(), format: "jsonl" },
      limit: 2,
      columns: ["id"],
    },
    permissions,
  ),
);
assert.deepEqual(scalarOnly.sample.rows, [[1], [2]]);
function ambiguousPreviewPath() {
  const file = join(data, "nested-preview.jsonl");
  writeFileSync(
    file,
    '{"id":1,"nested":{"secret":"PRIVATE_PREVIEW_NESTED"}}\n{"id":2,"nested":{}}\n',
  );
  return file;
}
checks.push(
  "Malformed or over-budget prefixes return no partial sample, while explicit scalar selections exclude nested business values",
);
const drafted = passed(
  operation(
    "connection_drafts",
    {
      ...selection,
      options: schemaOptions,
      acceptKeys: true,
      tables: tables.map((source, i) => ({
        source,
        name: ["first_json", "second_jsonl"][i],
      })),
    },
    permissions,
  ),
);
for (const table of drafted.tables) {
  assert.equal(table.sampling.rowCount, 2);
  const definition = parse(readFileSync(join(root, table.file), "utf8"));
  assert.ok(
    definition.schema[0].properties.every((c) => !c.required && !c.primaryKey),
  );
}
const ambiguous = join(data, "ambiguous.jsonl");
writeFileSync(
  ambiguous,
  '{"id":1,"nested":{"private":"PRIVATE_NESTED"},"nullOnly":null,"mixed":1,"wide":9223372036854775808}\n{"id":2,"nested":{},"nullOnly":null,"mixed":"x","wide":9223372036854775809}\n',
);
const skipped = passed(
  command(
    "connection",
    "drafts",
    "starter",
    "--executor",
    providerRef,
    "--tables",
    JSON.stringify([
      { source: { path: ambiguous, format: "jsonl" }, name: "ambiguous" },
    ]),
    "--options",
    JSON.stringify(schemaOptions),
  ),
);
assert.equal(skipped.tables[0].fields, 1);
assert.equal(skipped.tables[0].skipped.length, 4);
assert.doesNotMatch(JSON.stringify(skipped), /PRIVATE_NESTED/);
checks.push(
  "Complete JSON/JSONL draft selections retain sample evidence, never infer keys or required fields, and explain nested, all-null, mixed and integer-range omissions",
);
const draftsBefore = readdirSync(join(root, "contracts/discovery/dev/starter"));
writeFileSync(jsonlFile, "PRIVATE_BROKEN_LAST");
const failedDraft = operation(
  "connection_drafts",
  {
    ...selection,
    options: schemaOptions,
    tables: tables.map((source, i) => ({
      source,
      name: ["first_json", "second_jsonl"][i],
    })),
  },
  permissions,
);
assert.equal(failedDraft.ok, false);
assert.doesNotMatch(JSON.stringify(failedDraft), /PRIVATE_BROKEN_LAST/);
assert.deepEqual(
  readdirSync(join(root, "contracts/discovery/dev/starter")),
  draftsBefore,
);
writeFileSync(jsonlFile, jsonlText);
const recovered = passed(
  operation(
    "connection_drafts",
    {
      ...selection,
      options: schemaOptions,
      tables: tables.map((source, i) => ({
        source,
        name: ["first_json", "second_jsonl"][i],
      })),
    },
    permissions,
  ),
);
assert.equal(recovered.tables.length, 2);
checks.push(
  "A malformed last JSONL file creates no partial contract selection or payload-bearing diagnostic; repaired input recovers the complete selection",
);
const proposal = passed(
  operation(
    "connection_flow_review",
    {
      connection: "starter",
      id: "files_schema_snapshot",
      provider: "local",
      executor: providerRef,
      receipt: recovered.receipt,
      tables: recovered.tables.map((table) => ({
        id: table.id,
        table: table.name,
        contract: table.file,
      })),
    },
    ["--allow-write"],
  ),
);
passed(operation("apply", { proposal }, ["--allow-write"]));
for (const table of recovered.tables) {
  const path = join(root, table.file),
    definition = parse(readFileSync(path, "utf8"));
  const id = definition.schema[0].properties.find(
    (field) => field.name === "id",
  );
  id.required = true;
  id.primaryKey = true;
  writeFileSync(path, stringify(definition));
}
passed(
  operation("connection_prepare", { flow: "files_schema_snapshot" }, [
    "--allow-write",
  ]),
);
passed(command("check"));
passed(command("build"));
passed(command("runtime", "prepare"));
for (const action of ["discover", "review", "approve"])
  passed(command("run", "--action", action));
const run = passed(command("run", "--run-id", "json-schema-initial"));
assert.deepEqual(
  Object.fromEntries(
    run.result.flows[0].tables.map((table) => [table.stream, table.rows]),
  ),
  { first_json: 3, second_jsonl: 2 },
);
checks.push(
  "Reviewed source drafts bind through a compiler proposal and execute both complete JSON/JSONL files with explicitly reviewed key quality in the installed local provider",
);
const walk = (folder) =>
  readdirSync(folder, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory()
      ? walk(join(folder, entry.name))
      : [join(folder, entry.name)],
  );
writeFileSync(jsonlFile, jsonlText.replace('"id":2', '"id":1'));
const badQuality = command("run", "--run-id", "json-schema-quality");
assert.equal(badQuality.ok, false);
assert.equal(badQuality.diagnostics[0].code, "QUALITY_FAILED");
assert.ok(
  !walk(join(root, "build/generated/data")).some((path) =>
    path.includes("/json-schema-quality/"),
  ),
);
writeFileSync(jsonlFile, jsonlText);
passed(command("run", "--retry", "json-schema-quality"));
checks.push(
  "Required key quality rejects duplicate JSONL records before any table publication; correction and retry of the same run succeed",
);
for (const file of readdirSync(join(root, ".ingestron/source-access")).filter(
  (file) => file.endsWith(".json"),
))
  assert.doesNotMatch(
    readFileSync(join(root, ".ingestron/source-access", file), "utf8"),
    /PRIVATE_SCHEMA_RECORD|PRIVATE_SCHEMA_JSONL|PRIVATE_NESTED|PRIVATE_PARQUET_PREVIEW|files-private-preview|PRIVATE_BROKEN_FORMAT_ROW|PRIVATE_BROKEN_PARQUET|PRIVATE_BROKEN_LAST|PRIVATE_PREFIX_PREVIEW|PRIVATE_PREVIEW_NESTED|PRIVATE_MALFORMED_PREFIX|PRIVATE_UNREAD_SUFFIX|"rows"/,
  );
for (const table of recovered.tables)
  assert.doesNotMatch(
    readFileSync(join(root, table.file), "utf8"),
    /PRIVATE_SCHEMA_RECORD|PRIVATE_SCHEMA_JSONL/,
  );
checks.push(
  "Private receipts and suggested contract files retain schema and sample counts without any synthetic business values or row payload",
);
const archives = Object.fromEntries(
  ["core", "cli"].map((name) => {
    const path = resolve(options[name + "-archive"]);
    return [
      name,
      {
        path,
        sha256: createHash("sha256").update(readFileSync(path)).digest("hex"),
      },
    ];
  }),
);
writeFileSync(
  options.proof,
  JSON.stringify(
    {
      apiVersion: "ingestron.files-schema-acceptance/v1",
      result: "passed",
      root,
      cli,
      sourceRef,
      providerRef,
      sourceCommit,
      providerCommit,
      archives,
      cacheReuse: prepared.reused,
      checks,
      limits: [
        "Synthetic local flat JSON/JSONL only; unread prefixes are not full-file validation",
        "Remote inference, nested mapping and vendor qualification remain separate",
        "No publishing, live account/workspace changes or external-source access",
      ],
    },
    null,
    2,
  ) + "\n",
);
console.log(JSON.stringify({ result: "passed", checks: checks.length, root }));
