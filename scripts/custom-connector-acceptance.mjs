/** Immutable installed custom connector journey; synthetic local files only. */
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
const base = mkdtempSync(join(resolve(options.out), "custom-connector-"));
const root = join(base, "project");
mkdirSync(root);
execFileSync(
  process.execPath,
  [
    resolve(options.connectors, "scripts/new-connector.mjs"),
    "demo-source",
    "--label",
    "Synthetic custom source",
    "--repository",
    "https://example.invalid/synthetic/custom-source",
    "--out",
    join(root, "source"),
  ],
  { stdio: "pipe" },
);
cpSync(resolve(options.provider, "plugin"), join(root, "provider/plugin"), {
  recursive: true,
});
const version = JSON.parse(
  readFileSync(join(root, "source/connector.yaml"), "utf8"),
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
    "Immutable custom connector acceptance",
  );
  git(directory, "tag", tag);
}
const sourceRef = "example/custom/connector.yaml@" + version,
  providerRef = "example/local/plugin/provider.yaml@" + providerVersion;
const data = join(root, "data");
mkdirSync(data);
const schema = {
  type: "object",
  properties: { id: { type: "integer" }, label: { type: "string" } },
  required: ["id", "label"],
  additionalProperties: false,
};
const first =
  '{"id":9007199254740993,"label":"custom-private-preview"}\n{"id":2,"label":"second"}\n{"id":3,"label":"third"}\n';
const second = '{"id":1,"label":"second-table"}\n';
for (const [name, content] of [
  ["first", first],
  ["second", second],
]) {
  writeFileSync(join(data, name + ".jsonl"), content);
  writeFileSync(
    join(data, name + ".jsonl.schema.json"),
    JSON.stringify(schema),
  );
}
const contract = (name) => ({
  apiVersion: "v3.1.0",
  kind: "DataContract",
  id: "custom-" + name,
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
  id: "custom_connector_acceptance",
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
      settings: { directory: data },
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
  "Generated standalone package installs and locks an immutable source/runtime and provider snapshot through the installed CLI/core",
];
const cache = join(root, ".ingestron/runtime-cache");
cpSync(realpathSync(options.cache), cache, { recursive: true });
if (options.fresh !== "true")
  cpSync(realpathSync(options.cache), join(root, ".ingestron/runtimes"), {
    recursive: true,
  });
const rawAssets = JSON.parse(
  readFileSync(join(root, "source/runtime.json"), "utf8"),
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
const prepared = passed(
  operation("connection_runtime_prepare", selection, [
    ...permissions,
    "--allow-network",
  ]),
);
assert.equal(prepared.reused, options.fresh !== "true");
passed(operation("connection_test", selection, permissions));
const page = passed(
  operation("connection_inventory", { ...selection, limit: 1 }, permissions),
);
assert.equal(page.tables[0].name, "first.jsonl");
assert.ok(page.nextCursor);
const next = passed(
  operation(
    "connection_inventory",
    { ...selection, limit: 1, cursor: page.nextCursor },
    permissions,
  ),
);
assert.equal(next.tables[0].name, "second.jsonl");
assert.equal(next.nextCursor, undefined);
writeFileSync(
  join(data, "first.jsonl"),
  "ROW_VALUES_MUST_NOT_BE_READ_FOR_METADATA\n",
);
const metadata = passed(
  operation(
    "connection_metadata",
    {
      ...selection,
      tables: [{ path: "first.jsonl" }, { path: "second.jsonl" }],
    },
    permissions,
  ),
);
assert.equal(metadata.tables.length, 2);
assert.deepEqual(
  metadata.tables[0].columns.map((c) => c.name),
  ["id", "label"],
);
writeFileSync(join(data, "first.jsonl"), first);
checks.push(
  "Source access tests the directory, pages both tables and lists declared fields without reading JSON Lines record values",
);
const request = { ...selection, source: { path: "first.jsonl" }, limit: 1 };
assert.equal(
  operation("connection_sample", request, ["--allow-write"]).ok,
  false,
);
assert.equal(
  operation("connection_sample", { ...request, limit: 51 }, permissions).ok,
  false,
);
const preview = passed(operation("connection_sample", request, permissions));
assert.deepEqual(preview.sample.rows, [
  ["9007199254740993", "custom-private-preview"],
]);
assert.equal(preview.sample.truncated, true);
const terminal = passed(
  command(
    "connection",
    "sample",
    "starter",
    "--executor",
    providerRef,
    "--source",
    JSON.stringify(request.source),
    "--limit",
    "1",
  ),
);
assert.deepEqual(terminal.sample, preview.sample);
const sdk = passed(
  await executeAsync(
    { root, allowWrite: true, allowExecute: true },
    "connection_sample",
    request,
  ),
);
assert.deepEqual(sdk.sample, preview.sample);
for (const path of ["../first.jsonl", join(data, "first.jsonl")])
  assert.equal(
    operation(
      "connection_sample",
      { ...request, source: { path } },
      permissions,
    ).ok,
    false,
  );
checks.push(
  "Installed SDK and CLI operation/command samples agree, preserve int64 strings and reject execution denial, invalid limits and directory escape",
);
for (const allow of [false, true]) {
  const server = createServer(root, allow, "dev", false, allow),
    client = new Client({ name: "synthetic-custom-source", version: "1.0.0" }),
    [a, b] = InMemoryTransport.createLinkedPair();
  await server.connect(a);
  await client.connect(b);
  try {
    const tools = await client.listTools();
    assert.equal(
      tools.tools.some((t) => t.name === "ingestron_connection_sample"),
      allow,
    );
    if (allow) {
      const value = JSON.parse(
        (
          await client.callTool({
            name: "ingestron_connection_sample",
            arguments: request,
          })
        ).content[0].text,
      );
      assert.deepEqual(passed(value).sample, preview.sample);
    }
  } finally {
    await client.close();
    await server.close();
  }
}
checks.push(
  "Installed MCP exposes source sampling only with explicit write/execution opt-ins and returns the same bounded sample",
);
for (const file of readdirSync(join(root, ".ingestron/source-access")).filter(
  (f) => f.endsWith(".json"),
))
  assert.doesNotMatch(
    readFileSync(join(root, ".ingestron/source-access", file), "utf8"),
    /custom-private-preview|"rows"/,
  );
checks.push(
  "Persistent source receipts contain no sample rows or business values",
);
project.flows = [
  {
    apiVersion: "ingestron.flow/v1",
    kind: "ingestion",
    id: "custom_snapshot",
    provider: "local",
    ingestion: { connection: "starter", execution: { mode: "local" } },
    tables: Object.fromEntries(
      ["first", "second"].map((name) => [
        name,
        { source: { path: name + ".jsonl" }, contract: contract(name) },
      ]),
    ),
  },
];
writeFileSync(join(root, "project.yaml"), stringify(project));
passed(command("check"));
passed(command("build"));
passed(command("runtime", "prepare"));
checks.push(
  "Generated flow runtime is prepared separately from source-access runtime using the same hash-locked dependency contract",
);
for (const action of ["discover", "review", "approve"])
  passed(command("run", "--action", action));
const run = passed(command("run", "--run-id", "custom-initial"));
assert.deepEqual(
  Object.fromEntries(run.result.flows[0].tables.map((t) => [t.stream, t.rows])),
  { first: 3, second: 1 },
);
checks.push(
  "Installed core/local provider builds and executes the custom two-table reviewed snapshot with contract quality and exact record counts",
);
writeFileSync(join(data, "second.jsonl"), "SOURCE_VALUE_MUST_STAY_PRIVATE\n");
const failed = command("run", "--run-id", "custom-source-failure");
assert.equal(failed.ok, false);
assert.doesNotMatch(JSON.stringify(failed), /SOURCE_VALUE_MUST_STAY_PRIVATE/);
const walk = (folder) =>
  readdirSync(folder, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(join(folder, e.name)) : [join(folder, e.name)],
  );
assert.ok(
  !walk(join(root, "build/generated/data")).some((f) =>
    f.includes("/custom-source-failure/"),
  ),
);
writeFileSync(join(data, "second.jsonl"), second);
passed(command("run", "--retry", "custom-source-failure"));
checks.push(
  "A malformed last table publishes no first-table partial snapshot or payload-bearing error; repaired source retries the same run successfully",
);
writeFileSync(
  join(data, "second.jsonl"),
  '{"id":1,"label":"private-duplicate"}\n{"id":1,"label":"other"}\n',
);
const duplicate = command("run", "--run-id", "custom-quality-failure");
assert.equal(duplicate.ok, false);
assert.equal(duplicate.diagnostics[0].code, "QUALITY_FAILED");
const measured = passed(
  operation("run_status", { id: "custom-quality-failure" }),
);
assert.match(JSON.stringify(measured.quality), /key-unique/);
assert.doesNotMatch(JSON.stringify(duplicate), /private-duplicate/);
assert.ok(
  !walk(join(root, "build/generated/data")).some((f) =>
    f.includes("/custom-quality-failure/"),
  ),
);
writeFileSync(join(data, "second.jsonl"), second);
passed(command("run", "--retry", "custom-quality-failure"));
checks.push(
  "Required contract key quality rejects a duplicate before publication without business values; correction and same-run retry succeed",
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
      apiVersion: "ingestron.custom-connector-acceptance/v1",
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
        "Synthetic local JSON Lines source only; adapted vendor connectors remain unqualified",
        "No official alias, public publishing, cloud execution or account/workspace ownership change",
        "Studio/browser and editor qualification remains separate",
      ],
    },
    null,
    2,
  ) + "\n",
);
console.log(JSON.stringify({ result: "passed", checks: checks.length, root }));
