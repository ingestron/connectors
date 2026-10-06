/** Installed SFTP and Graph folder/list selection, drafting, sampling, quality and recovery. */
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
const kinds = ["sftp", "sharepoint", "onedrive"];
let config;
if (process.argv[2] !== "--verify") {
  for (const name of [
    "PROVIDER",
    "OUTPUT",
    "PROOF",
    "CACHE",
    "PYTHON",
    "SFTP_IMAGE",
    "CORE_ARCHIVE",
    "CLI_ARCHIVE",
  ])
    assert.ok(
      process.env["INGESTRON_ACCEPTANCE_" + name],
      "Set acceptance " + name,
    );
  const base = resolve(process.env.INGESTRON_ACCEPTANCE_OUTPUT);
  mkdirSync(base, { recursive: true });
  const root = mkdtempSync(resolve(base, "folder-inventory-"));
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
      "Immutable folder inventory",
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
    git(source, "tag", kind + "-" + manifest.version);
    const reference =
      "example/folder/connectors/" +
      kind +
      "/connector.yaml@" +
      manifest.version;
    adapter.installPackage(root, reference, {
      fromGit: source,
      tagPrefix: kind + "-",
    });
    packages[kind] = reference;
    records.push({
      kind,
      version: manifest.version,
      reference,
      runtimeSha256: manifest.runtime.sha256,
    });
  }
  const secret = { $secret: { env: "INGESTRON_GRAPH_FIXTURE_SECRET" } };
  const graph = {
    tenant_id: "11111111-2222-3333-4444-555555555555",
    client_id: "66666666-7777-8888-9999-000000000000",
    client_secret: secret,
  };
  // The fixture supplies its fresh SFTP endpoint and public pin before verification.
  const settings = {
    sftp: {
      host: "127.0.0.1",
      port: 22,
      user: "reader",
      private_key: { $secret: { env: "INGESTRON_SFTP_FIXTURE_KEY" } },
      host_key: "ssh-ed25519 pending-fixture-public-pin",
    },
    sharepoint: {
      ...graph,
      site: "https://contoso.sharepoint.com/sites/finance",
    },
    onedrive: { ...graph, user: "reader@contoso.example" },
  };
  writeFileSync(
    resolve(root, "project.yaml"),
    stringify({
      apiVersion: "ingestron.project/v1",
      id: "folder_inventory_acceptance",
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
  cpSync(
    realpathSync(process.env.INGESTRON_ACCEPTANCE_CACHE),
    resolve(root, ".ingestron/runtimes"),
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
    sftpImage: process.env.INGESTRON_ACCEPTANCE_SFTP_IMAGE,
    archives: Object.fromEntries(
      ["core", "cli"].map((name) => {
        const path = resolve(
          process.env[
            "INGESTRON_ACCEPTANCE_" + name.toUpperCase() + "_ARCHIVE"
          ],
        );
        return [name, { path, sha256: hash(path) }];
      }),
    ),
  };
  const path = resolve(root, "acceptance.json");
  writeFileSync(path, JSON.stringify(config, null, 2));
  const child = spawnSync(
    process.env.INGESTRON_ACCEPTANCE_PYTHON,
    [resolve(owner, "scripts/folder-inventory-acceptance.py"), path],
    {
      encoding: "utf8",
      timeout: 600000,
      env: process.env,
    },
  );
  process.stdout.write(child.stdout ?? "");
  process.stderr.write(child.stderr ?? "");
  assert.equal(child.status, 0, "Loopback installed acceptance failed");
} else {
  config = JSON.parse(readFileSync(process.argv[3], "utf8"));
  const root = config.root,
    permissions = ["--allow-write", "--allow-execute"];
  const invoke = (args, input) => {
    const child = spawnSync(
      process.execPath,
      [cli, "--project", root, "--json", "--no-input", ...args],
      {
        encoding: "utf8",
        input: input && JSON.stringify(input),
        timeout: 120000,
      },
    );
    assert.equal(child.error, undefined);
    assert.ok(child.stdout.trim(), child.stderr);
    return JSON.parse(child.stdout);
  };
  const operation = (name, args = {}, flags = permissions) =>
    invoke(["operation", name, ...flags], args);
  const command = (...args) => invoke(args);
  const initialProject = parse(
    readFileSync(resolve(root, "project.yaml"), "utf8"),
  );
  initialProject.connections.sftp.settings.port = config.sftpPort;
  initialProject.connections.sftp.settings.host_key = config.sftpHostKey;
  writeFileSync(resolve(root, "project.yaml"), stringify(initialProject));
  const context = { root, allowWrite: true, allowExecute: true };
  const scopeFor = (kind) => ({
    directory:
      kind === "sftp"
        ? "upload"
        : kind === "sharepoint"
          ? "Shared Documents/retail"
          : "retail",
    format: "all",
  });
  const control = async (action, kind) => {
    const response = await fetch(config.controlUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, kind }),
    });
    assert.equal(response.status, 200);
    assert.equal((await response.json()).ok, true);
  };
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
  const walk = (folder) =>
    readdirSync(folder, { withFileTypes: true }).flatMap((e) =>
      e.isDirectory()
        ? walk(resolve(folder, e.name))
        : [resolve(folder, e.name)],
    );
  const noPublished = (id) =>
    assert.ok(
      !walk(resolve(root, "build/generated/data")).some((p) =>
        p.includes("/" + id + "/"),
      ),
    );
  const contract = (name) => ({
    apiVersion: "v3.1.0",
    kind: "DataContract",
    id: "folder-" + name,
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
  let result = "failed";
  try {
    for (const record of config.records) {
      const selection = {
          connection: record.kind,
          executor: config.providerRef,
        },
        scope = scopeFor(record.kind);
      const described = passed(
        await executeAsync(context, "connection_access", selection),
      );
      assert.ok(described.actions.includes("inventory"));
      assert.ok(described.inventoryScopeSchema.properties.directory);
      const first = passed(
        await executeAsync(context, "connection_inventory", {
          ...selection,
          scope,
          limit: 2,
        }),
      );
      assert.deepEqual(
        first.tables.map((t) => t.name),
        ["customers.tsv", "orders.csv"],
      );
      assert.ok(first.nextCursor);
      assert.ok(first.tables.every((t) => !t.columns));
      const next = passed(
        operation("connection_inventory", {
          ...selection,
          scope,
          limit: 2,
          cursor: first.nextCursor,
        }),
      );
      assert.deepEqual(
        next.tables.map((t) => t.name),
        ["products.csv"],
      );
      assert.equal(next.nextCursor, undefined);
      const terminal = passed(
        invoke([
          "connection",
          "inventory",
          record.kind,
          "--executor",
          config.providerRef,
          "--scope",
          JSON.stringify(scope),
          "--limit",
          "2",
        ]),
      );
      assert.deepEqual(terminal.tables, first.tables);
      const filtered = passed(
        operation("connection_inventory", {
          ...selection,
          scope,
          query: "products",
          limit: 2,
        }),
      );
      if (record.kind === "sftp") assert.equal(filtered.tables.length, 1);
      else {
        assert.deepEqual(filtered.tables, []);
        assert.ok(filtered.nextCursor);
        assert.equal(
          passed(
            operation("connection_inventory", {
              ...selection,
              scope,
              query: "products",
              limit: 2,
              cursor: filtered.nextCursor,
            }),
          ).tables.length,
          1,
        );
      }
      for (const changed of [
        { query: "changed" },
        { scope: { directory: "elsewhere" } },
      ]) {
        const denial = operation("connection_inventory", {
          ...selection,
          scope,
          cursor: first.nextCursor,
          ...changed,
        });
        assert.equal(denial.ok, false);
        assert.doesNotMatch(
          JSON.stringify(denial),
          /synthetic-secret|PRIVATE_BODY_VALUE/,
        );
      }
      assert.equal(
        operation("connection_inventory", { ...selection, scope }, [
          "--allow-write",
        ]).ok,
        false,
      );
      const malformed = operation("connection_inventory", {
        ...selection,
        scope: {
          directory:
            record.kind === "sharepoint"
              ? "Shared Documents/missing"
              : "missing",
        },
      });
      assert.equal(malformed.ok, false);
      assert.doesNotMatch(
        JSON.stringify(malformed),
        /synthetic-secret|PRIVATE_BODY_VALUE/,
      );
      assert.deepEqual(
        passed(
          operation("connection_inventory", { ...selection, scope, limit: 2 }),
        ).tables,
        first.tables,
      );
      const server = createServer(root, true, "dev", false, true),
        client = new Client({ name: "folder-inventory", version: "1.0.0" });
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
      const sources = [...first.tables, ...next.tables].map((t) => t.source);
      const metadata = passed(
        operation("connection_metadata", { ...selection, tables: sources }),
      );
      assert.equal(metadata.tables.length, 3);
      for (const table of metadata.tables)
        assert.deepEqual(
          table.columns.map((c) => c.name),
          ["id", "label"],
        );
      const drafts = passed(
        operation("connection_contracts", {
          ...selection,
          receipt: metadata.receipt,
          tables: metadata.tables.map((t, i) => ({
            id: t.id,
            name: ["customers", "orders", "products"][i],
          })),
        }),
      );
      assert.equal(drafts.tables.length, 3);
      for (const table of drafts.tables)
        assert.equal(
          parse(readFileSync(resolve(root, table.file), "utf8")).schema[0]
            .properties.length,
          2,
        );
      const preview = passed(
        operation("connection_sample", {
          ...selection,
          source: sources[1],
          limit: 2,
        }),
      );
      assert.equal(preview.sample.rows.length, 2);
      assert.match(JSON.stringify(preview.sample.rows), /PRIVATE_PREVIEW/);
      const flowId = record.kind + "_snapshot",
        project = parse(readFileSync(resolve(root, "project.yaml"), "utf8"));
      project.flows = [
        {
          apiVersion: "ingestron.flow/v1",
          kind: "ingestion",
          id: flowId,
          provider: "local",
          ingestion: { connection: record.kind, execution: { mode: "local" } },
          tables: Object.fromEntries(
            sources.map((source, i) => {
              const name = ["customers", "orders", "products"][i];
              return [name, { source, contract: contract(name) }];
            }),
          ),
        },
      ];
      writeFileSync(resolve(root, "project.yaml"), stringify(project));
      passed(command("check"));
      passed(command("build"));
      passed(command("runtime", "prepare"));
      for (const action of ["discover", "review", "approve"])
        passed(command("run", "--action", action));
      const initial = passed(
        command("run", "--run-id", record.kind + "-initial"),
      );
      assert.deepEqual(
        Object.fromEntries(
          initial.result.flows[0].tables.map((t) => [t.stream, t.rows]),
        ),
        { customers: 1, orders: 3, products: 2 },
      );
      await control("source-failure", record.kind);
      const failureId = record.kind + "-source-failure",
        failure = command("run", "--run-id", failureId);
      assert.equal(failure.ok, false);
      assert.doesNotMatch(
        JSON.stringify(failure),
        /PRIVATE_BODY_VALUE|PRIVATE_PREVIEW|synthetic-secret/,
      );
      noPublished(failureId);
      await control("repair", record.kind);
      passed(command("run", "--retry", failureId));
      await control("quality-failure", record.kind);
      const qualityId = record.kind + "-quality-failure",
        quality = command("run", "--run-id", qualityId);
      assert.equal(quality.ok, false);
      assert.equal(quality.diagnostics[0].code, "QUALITY_FAILED");
      assert.doesNotMatch(
        JSON.stringify(quality),
        /PRIVATE_DUPLICATE|PRIVATE_PREVIEW|synthetic-secret/,
      );
      noPublished(qualityId);
      assert.match(
        JSON.stringify(
          passed(operation("run_status", { id: qualityId })).quality,
        ),
        /key-unique/,
      );
      await control("repair", record.kind);
      passed(command("run", "--retry", qualityId));
      Object.assign(record, {
        sdkCliMcpParity: true,
        pageCounts: [2, 1],
        changedScopeDenied: true,
        permissionDenied: true,
        metadataColumns: 2,
        durableContractDrafts: 3,
        boundedSampleRows: 2,
        snapshotCounts: { customers: 1, orders: 3, products: 2 },
        sourceFailureAtomic: true,
        requiredQualityAtomic: true,
        sameRunRetriesPassed: true,
      });
      console.log(
        record.kind +
          " installed inventory, draft, sample, quality and retry passed",
      );
    }
    const selection = {
      connection: "sharepoint",
      executor: config.providerRef,
    };
    const lists = passed(
      operation("connection_inventory", {
        ...selection,
        scope: { entity: "list" },
        limit: 2,
      }),
    );
    assert.equal(lists.tables.length, 1);
    assert.equal(lists.tables[0].name, "Retail Customers");
    assert.ok(lists.nextCursor);
    const listNext = passed(
      operation("connection_inventory", {
        ...selection,
        scope: { entity: "list" },
        limit: 2,
        cursor: lists.nextCursor,
      }),
    );
    assert.equal(listNext.tables[0].name, "Retail Orders");
    assert.match(lists.tables[0].source.path, /Lists\/[a-f0-9-]{36}/);
    const friendlyQuery = passed(
      operation("connection_inventory", {
        ...selection,
        scope: { entity: "list" },
        query: "RETAIL",
        limit: 2,
      }),
    );
    assert.equal(friendlyQuery.tables[0].name, "Retail Customers");
    const friendlyNext = passed(
      operation("connection_inventory", {
        ...selection,
        scope: { entity: "list" },
        query: "RETAIL",
        limit: 2,
        cursor: friendlyQuery.nextCursor,
      }),
    );
    assert.equal(friendlyNext.tables[0].name, "Retail Orders");
    const source = listNext.tables[0].source,
      metadata = passed(
        operation("connection_metadata", { ...selection, tables: [source] }),
      );
    assert.deepEqual(
      metadata.tables[0].columns.map((c) => c.name),
      ["id", "label"],
    );
    const draft = passed(
      operation("connection_contracts", {
        ...selection,
        receipt: metadata.receipt,
        tables: [{ id: metadata.tables[0].id, name: "list_orders" }],
      }),
    );
    assert.equal(draft.tables.length, 1);
    const sample = passed(
      operation("connection_sample", { ...selection, source, limit: 2 }),
    );
    assert.equal(sample.sample.rows.length, 2);
    config.listAcceptance = {
      nativeIdSelection: true,
      friendlyNames: true,
      displayedNameQuery: true,
      pageCounts: [1, 1],
      metadataColumns: 2,
      durableDrafts: 1,
      sampleRows: 2,
    };
    for (const file of readdirSync(
      resolve(root, ".ingestron/source-access"),
    ).filter((f) => f.endsWith(".json")))
      assert.doesNotMatch(
        readFileSync(resolve(root, ".ingestron/source-access", file), "utf8"),
        /synthetic-secret|PRIVATE_BODY_VALUE|PRIVATE_PREVIEW|PRIVATE_DUPLICATE|"rows"|"settings"/,
      );
    result = "passed";
  } finally {
    writeFileSync(
      config.proof,
      JSON.stringify(
        {
          apiVersion: "ingestron.folder-inventory-acceptance/v1",
          result,
          ...config,
          limits:
            "Immutable installed CLI/core/source/provider and locked prepared dependencies. Real local OpenSSH SFTP; Graph redirected to socket-fenced protocol fixture. Synthetic data only; no live Graph tenant, publication or deployment.",
        },
        null,
        2,
      ) + "\n",
    );
  }
}
