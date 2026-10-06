/** Three immutable cloud sources through installed SDK, CLI and MCP; loopback only. */
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
import { resolve, dirname } from "node:path";
import { createHash } from "node:crypto";
import { execFileSync, spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
const script = fileURLToPath(import.meta.url),
  owner = resolve(dirname(script), "..");
const cliRoot = realpathSync(process.env.INGESTRON_ACCEPTANCE_CLI_PACKAGE);
const coreRoot = realpathSync(resolve(cliRoot, "../@ingestron/core"));
const cli = resolve(cliRoot, "build/cli/cli/index.js");
const require = createRequire(resolve(cliRoot, "package.json"));
const { parse, stringify } = require("yaml");
const { executeAsync } = await import(
  pathToFileURL(resolve(coreRoot, "dist/sdk/index.js")).href
);
const adapter = await import(
  pathToFileURL(resolve(coreRoot, "dist/sdk/adapter.js")).href
);
const hash = (path) =>
  createHash("sha256").update(readFileSync(path)).digest("hex");
const passed = (r) => {
  assert.equal(r.ok, true, JSON.stringify(r));
  return r.result;
};
const kinds = ["s3", "gcs", "azure-blob"];
let config;
if (process.argv[2] !== "--verify") {
  for (const name of ["PROVIDER", "OUTPUT", "PROOF", "CACHE", "PYTHON"])
    assert.ok(
      process.env["INGESTRON_ACCEPTANCE_" + name],
      "Set acceptance " + name,
    );
  const base = resolve(process.env.INGESTRON_ACCEPTANCE_OUTPUT);
  mkdirSync(base, { recursive: true });
  const root = mkdtempSync(resolve(base, "cloud-inventory-"));
  const source = resolve(root, "source"),
    provider = resolve(root, "provider");
  mkdirSync(source);
  for (const kind of kinds)
    cpSync(
      resolve(owner, "connectors", kind),
      resolve(source, "connectors", kind),
      { recursive: true },
    );
  cpSync(
    resolve(process.env.INGESTRON_ACCEPTANCE_PROVIDER, "plugin"),
    resolve(provider, "plugin"),
    {
      recursive: true,
      filter: (p) => !p.includes("__pycache__"),
    },
  );
  const git = (cwd, ...args) =>
    execFileSync("git", args, { cwd, encoding: "utf8", stdio: "pipe" }).trim();
  for (const cwd of [source, provider]) {
    git(cwd, "init", "-q");
    git(cwd, "add", ".");
    git(
      cwd,
      "-c",
      "user.name=Synthetic fixture",
      "-c",
      "user.email=fixture@example.invalid",
      "commit",
      "-qm",
      "Immutable cloud file inventory",
    );
  }
  const providerVersion = parse(
    readFileSync(resolve(provider, "plugin/provider.yaml"), "utf8"),
  ).version;
  git(provider, "tag", providerVersion);
  const providerRef = "example/local/plugin/provider.yaml@" + providerVersion;
  adapter.installPackage(root, providerRef, { fromGit: provider });
  const packages = { local: providerRef },
    records = [];
  for (const kind of kinds) {
    const manifest = parse(
      readFileSync(
        resolve(source, "connectors", kind, "connector.yaml"),
        "utf8",
      ),
    );
    git(source, "tag", manifest.version);
    const reference =
      "example/cloud/connectors/" +
      kind +
      "/connector.yaml@" +
      manifest.version;
    adapter.installPackage(root, reference, { fromGit: source });
    packages[kind] = reference;
    records.push({
      kind,
      version: manifest.version,
      reference,
      runtimeSha256: manifest.runtime.sha256,
    });
  }
  const secret = { $secret: { env: "INGESTRON_CLOUD_FIXTURE_SECRET" } };
  const settings = {
    s3: {
      bucket: "syntheticretail",
      region: "us-east-1",
      access_key_id: "SYNTHETIC-KEY",
      secret_access_key: secret,
    },
    gcs: {
      bucket: "syntheticretail",
      access_key_id: "SYNTHETIC-KEY",
      secret_access_key: secret,
    },
    "azure-blob": {
      account: "syntheticretail",
      container: "bronze",
      sas_token: { $secret: { env: "INGESTRON_CLOUD_FIXTURE_SAS" } },
    },
  };
  writeFileSync(
    resolve(root, "project.yaml"),
    stringify({
      apiVersion: "ingestron.project/v1",
      id: "cloud_file_inventory",
      packages,
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
      connections: Object.fromEntries(
        kinds.map((kind) => [
          kind,
          {
            package: kind,
            sourceId: "synthetic",
            tenantId: "training",
            settings: settings[kind],
          },
        ]),
      ),
      flows: [],
    }),
  );
  cpSync(
    realpathSync(process.env.INGESTRON_ACCEPTANCE_CACHE),
    resolve(root, ".ingestron/runtime-cache"),
    { recursive: true },
  );
  config = {
    root,
    providerRef,
    records,
    sourceCommit: git(source, "rev-parse", "HEAD"),
    providerCommit: git(provider, "rev-parse", "HEAD"),
    cli,
    core: coreRoot,
    cliEntrySha256: hash(cli),
    proof: resolve(process.env.INGESTRON_ACCEPTANCE_PROOF),
    script,
  };
  const path = resolve(root, "acceptance.json");
  writeFileSync(path, JSON.stringify(config, null, 2));
  const child = spawnSync(
    process.env.INGESTRON_ACCEPTANCE_PYTHON,
    [resolve(owner, "scripts/remote-file-inventory-acceptance.py"), path],
    {
      encoding: "utf8",
      timeout: 600000,
      env: {
        ...process.env,
        INGESTRON_CLOUD_FIXTURE_SECRET: "synthetic-secret",
        INGESTRON_CLOUD_FIXTURE_SAS:
          "sv=2023-11-03&sp=rl&se=2099-01-01&spr=https&sig=synthetic-secret",
      },
    },
  );
  process.stdout.write(child.stdout ?? "");
  process.stderr.write(child.stderr ?? "");
  assert.equal(child.status, 0, "Loopback installed acceptance failed");
} else {
  config = JSON.parse(readFileSync(process.argv[3], "utf8"));
  const root = config.root,
    permissions = ["--allow-write", "--allow-execute"];
  const operation = (name, args, flags = permissions) => {
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
        ...flags,
      ],
      {
        encoding: "utf8",
        input: JSON.stringify(args),
        timeout: 120000,
      },
    );
    assert.equal(child.error, undefined);
    return JSON.parse(child.stdout);
  };
  const context = { root, allowWrite: true, allowExecute: true };
  const scope = { prefix: "retail/", format: "all" };
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
  let result = "failed";
  try {
    for (const record of config.records) {
      const selection = {
        connection: record.kind,
        executor: config.providerRef,
      };
      const described = passed(
        await executeAsync(context, "connection_access", selection),
      );
      assert.ok(described.actions.includes("inventory"));
      assert.ok(described.inventoryScopeSchema.properties.prefix);
      const first = passed(
        await executeAsync(context, "connection_inventory", {
          ...selection,
          scope,
          limit: 2,
        }),
      );
      assert.equal(first.tables.length, 2);
      assert.ok(first.nextCursor);
      const next = passed(
        operation("connection_inventory", {
          ...selection,
          scope,
          limit: 2,
          cursor: first.nextCursor,
        }),
      );
      assert.deepEqual(
        next.tables.map((t) => t.source),
        [{ path: "retail/sub/products.parquet", format: "parquet" }],
      );
      assert.equal(next.nextCursor, undefined);
      const terminal = spawnSync(
        process.execPath,
        [
          cli,
          "--project",
          root,
          "--json",
          "--no-input",
          "connection",
          "inventory",
          record.kind,
          "--executor",
          config.providerRef,
          "--scope",
          JSON.stringify(scope),
          "--limit",
          "2",
        ],
        { encoding: "utf8", timeout: 120000 },
      );
      assert.deepEqual(
        passed(JSON.parse(terminal.stdout)).tables,
        first.tables,
      );
      const filtered = passed(
        operation("connection_inventory", {
          ...selection,
          scope,
          query: "products",
          limit: 2,
        }),
      );
      assert.deepEqual(filtered.tables, []);
      assert.ok(filtered.nextCursor);
      const recovered = passed(
        operation("connection_inventory", {
          ...selection,
          scope,
          query: "products",
          limit: 2,
          cursor: filtered.nextCursor,
        }),
      );
      assert.equal(recovered.tables.length, 1);
      for (const args of [
        { ...selection, scope, query: "changed", cursor: first.nextCursor },
        {
          ...selection,
          scope: { prefix: "elsewhere/" },
          cursor: first.nextCursor,
        },
        {
          ...selection,
          scope: { directory: "/tmp", password: "PRIVATE_SCOPE_VALUE" },
        },
      ]) {
        const denied = operation("connection_inventory", args);
        assert.equal(denied.ok, false);
        assert.doesNotMatch(
          JSON.stringify(denied),
          /PRIVATE_SCOPE_VALUE|synthetic-secret/,
        );
      }
      assert.equal(
        operation("connection_inventory", { ...selection, scope }, [
          "--allow-write",
        ]).ok,
        false,
      );
      const failure = operation("connection_inventory", {
        ...selection,
        scope: { prefix: "malformed/" },
      });
      assert.equal(failure.ok, false);
      assert.doesNotMatch(
        JSON.stringify(failure),
        /PRIVATE_BODY_VALUE|synthetic-secret/,
      );
      const retry = passed(
        operation("connection_inventory", { ...selection, scope, limit: 2 }),
      );
      assert.deepEqual(retry.tables, first.tables);
      const server = createServer(root, true, "dev", false, true),
        client = new Client({ name: "cloud-inventory", version: "1.0.0" });
      const [a, b] = InMemoryTransport.createLinkedPair();
      await server.connect(a);
      await client.connect(b);
      try {
        const tools = await client.listTools();
        assert.ok(
          tools.tools.some((t) => t.name === "ingestron_connection_inventory"),
        );
        const mcp = JSON.parse(
          (
            await client.callTool({
              name: "ingestron_connection_inventory",
              arguments: { ...selection, scope, limit: 2 },
            })
          ).content[0].text,
        );
        assert.deepEqual(passed(mcp).tables, first.tables);
      } finally {
        await client.close();
        await server.close();
      }
      Object.assign(record, {
        sdkCliMcpParity: true,
        pageCounts: [2, 1],
        filteredCounts: [0, 1],
        changedCursorDenied: true,
        malformedResponseDenied: true,
        permissionDenied: true,
        recovered: true,
      });
      console.log(record.kind + " installed cloud file inventory passed");
    }
    for (const file of readdirSync(
      resolve(root, ".ingestron/source-access"),
    ).filter((f) => f.endsWith(".json")))
      assert.doesNotMatch(
        readFileSync(resolve(root, ".ingestron/source-access", file), "utf8"),
        /synthetic-secret|PRIVATE_BODY_VALUE|"rows"|"settings"/,
      );
    result = "passed";
  } finally {
    writeFileSync(
      config.proof,
      JSON.stringify(
        {
          apiVersion: "ingestron.cloud-file-inventory-acceptance/v1",
          result,
          ...config,
          limits:
            "Immutable installed CLI/core/source/provider with prepared locked dependencies; unmodified source protocols redirected to socket-fenced loopback fixtures. No business object downloads, vendor credentials or live cloud qualification.",
        },
        null,
        2,
      ) + "\n",
    );
  }
}
