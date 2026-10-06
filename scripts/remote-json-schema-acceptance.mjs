/** Installed six-source JSON schema suggestions, reviewed quality, snapshots and recovery. */
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
const kinds = ["sftp", "sharepoint", "onedrive", "s3", "gcs", "azure-blob"];
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
  const root = mkdtempSync(resolve(base, "remote-json-schema-"));
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
  const cloudSecret = { $secret: { env: "INGESTRON_CLOUD_FIXTURE_SECRET" } };
  const settings = {
    s3: {
      bucket: "syntheticretail",
      region: "us-east-1",
      access_key_id: "SYNTHETIC-KEY",
      secret_access_key: cloudSecret,
    },
    gcs: {
      bucket: "syntheticretail",
      access_key_id: "SYNTHETIC-KEY",
      secret_access_key: cloudSecret,
    },
    "azure-blob": {
      account: "syntheticretail",
      container: "bronze",
      sas_token: { $secret: { env: "INGESTRON_CLOUD_FIXTURE_SAS" } },
    },
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
    [resolve(owner, "scripts/remote-json-schema-acceptance.py"), path],
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
  const projectPath = resolve(root, "project.yaml"),
    initial = parse(readFileSync(projectPath, "utf8"));
  initial.connections.sftp.settings.port = config.sftpPort;
  initial.connections.sftp.settings.host_key = config.sftpHostKey;
  writeFileSync(projectPath, stringify(initial));
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
  const context = { root, allowWrite: true, allowExecute: true };
  const pathFor = (kind, file) =>
    (kind === "sftp"
      ? "upload/"
      : kind === "sharepoint"
        ? "Shared Documents/retail/"
        : "retail/") + file;
  const control = async (action, kind) => {
    const r = await fetch(config.controlUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, kind }),
    });
    assert.equal(r.status, 200);
  };
  const privateResult = (r) =>
    assert.doesNotMatch(
      JSON.stringify(r),
      /PRIVATE_JSON_RECORD|PRIVATE_BROKEN_JSON|PRIVATE_NESTED|synthetic-secret|ingestron-sample-/,
    );
  const walk = (folder) =>
    readdirSync(folder, { withFileTypes: true }).flatMap((e) =>
      e.isDirectory()
        ? walk(resolve(folder, e.name))
        : [resolve(folder, e.name)],
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
  let result = "failed";
  try {
    for (const record of config.records) {
      const selection = {
        connection: record.kind,
        executor: config.providerRef,
      };
      const source = {
          path: pathFor(record.kind, "orders.jsonl"),
          format: "jsonl",
        },
        other = {
          path: pathFor(record.kind, "customers.json"),
          format: "json",
        };
      const options = { sampleRecords: true, limit: 2 };
      const access = passed(
        await executeAsync(context, "connection_access", selection),
      );
      assert.deepEqual(
        access.metadataOptionsSchema.properties.sampleRecords.enum,
        [true],
      );
      for (const input of [
        {},
        { options: { sampleRecords: false } },
        { options: { sampleRecords: true, limit: 51 } },
      ]) {
        const denied = operation("connection_metadata", {
          ...selection,
          tables: [source],
          ...input,
        });
        assert.equal(denied.ok, false);
        privateResult(denied);
      }
      assert.equal(
        operation(
          "connection_metadata",
          { ...selection, tables: [source], options },
          ["--allow-write"],
        ).ok,
        false,
      );
      const metadata = passed(
        await executeAsync(context, "connection_metadata", {
          ...selection,
          tables: [source, other],
          options,
        }),
      );
      assert.equal(metadata.scope, "data");
      assert.equal(metadata.tables.length, 2);
      privateResult(metadata);
      for (const t of metadata.tables) {
        assert.deepEqual(t.source, t.source.format === "json" ? other : source);
        assert.equal(t.sampling.rowCount, 2);
        assert.equal(t.sampling.limit, 2);
        assert.equal(t.sampling.byteLimit, 1048576);
        assert.equal(t.sampling.truncated, true);
        assert.ok(t.columns.every((c) => c.nullable && !c.key));
      }
      const columns = Object.fromEntries(
        metadata.tables[0].columns.map((c) => [c.name, c]),
      );
      assert.equal(columns.id.type, "integer");
      assert.equal(columns.amount.type, "decimal");
      assert.equal(columns.amount.scale, 3);
      assert.equal(columns.active.type, "boolean");
      const cliMetadata = passed(
        operation("connection_metadata", {
          ...selection,
          tables: [source, other],
          options,
        }),
      );
      assert.deepEqual(cliMetadata.tables, metadata.tables);
      const server = createServer(root, true, "dev", false, true),
        client = new Client({ name: "remote-json-schema", version: "1.0.0" });
      const [a, b] = InMemoryTransport.createLinkedPair();
      await server.connect(a);
      await client.connect(b);
      try {
        const response = JSON.parse(
          (
            await client.callTool({
              name: "ingestron_connection_metadata",
              arguments: { ...selection, tables: [source, other], options },
            })
          ).content[0].text,
        );
        assert.deepEqual(passed(response).tables, metadata.tables);
      } finally {
        await client.close();
        await server.close();
      }
      const nested = passed(
        operation("connection_metadata", {
          ...selection,
          tables: [
            { path: pathFor(record.kind, "nested.jsonl"), format: "jsonl" },
          ],
          options,
        }),
      );
      assert.equal(
        nested.tables[0].columns.find((c) => c.name === "nested").supported,
        false,
      );
      privateResult(nested);
      for (const file of ["bad.jsonl", "oversized.jsonl"]) {
        const failure = operation("connection_metadata", {
          ...selection,
          tables: [
            source,
            { path: pathFor(record.kind, file), format: "jsonl" },
          ],
          options,
        });
        assert.equal(failure.ok, false);
        privateResult(failure);
      }
      const drafts = passed(
        operation("connection_contracts", {
          ...selection,
          receipt: metadata.receipt,
          tables: metadata.tables.map((t, i) => ({
            id: t.id,
            name: ["orders", "customers"][i],
          })),
        }),
      );
      assert.equal(drafts.tables.length, 2);
      assert.ok(drafts.tables.every((t) => t.sampling.rowCount === 2));
      const contracts = drafts.tables.map((t) =>
        parse(readFileSync(resolve(root, t.file), "utf8")),
      );
      for (const contract of contracts) {
        assert.ok(
          contract.schema[0].properties.every(
            (c) => !c.required && !c.primaryKey,
          ),
        );
        for (const field of contract.schema[0].properties) {
          field.required = true;
          if (field.name === "id") field.primaryKey = true;
        }
      }
      const project = parse(readFileSync(projectPath, "utf8"));
      project.flows = [
        {
          apiVersion: "ingestron.flow/v1",
          kind: "ingestion",
          id: record.kind + "_json_snapshot",
          provider: "local",
          ingestion: { connection: record.kind, execution: { mode: "local" } },
          tables: {
            orders: { source, contract: contracts[0] },
            customers: { source: other, contract: contracts[1] },
          },
        },
      ];
      writeFileSync(projectPath, stringify(project));
      const preview = passed(
        operation("connection_sample", { ...selection, source, limit: 2 }),
      );
      assert.equal(preview.sample.rows.length, 2);
      assert.match(JSON.stringify(preview.sample.rows), /9007199254740993/);
      passed(command("check"));
      passed(command("build"));
      passed(command("runtime", "prepare"));
      for (const action of ["discover", "review", "approve"])
        passed(command("run", "--action", action));
      const initial = passed(
        command("run", "--run-id", record.kind + "-json-initial"),
      );
      assert.deepEqual(
        Object.fromEntries(
          initial.result.flows[0].tables.map((t) => [t.stream, t.rows]),
        ),
        { orders: 3, customers: 3 },
      );
      const written = walk(resolve(root, "build/generated/data")).filter(
        (p) =>
          p.includes("/" + record.kind + "-json-initial/") &&
          p.endsWith(".parquet"),
      );
      assert.equal(written.length, 2);
      const runtimePython = resolve(
        root,
        ".ingestron/runtime-cache",
        readdirSync(resolve(root, ".ingestron/runtime-cache"))[0],
        "bin/python",
      );
      execFileSync(
        runtimePython,
        [
          "-c",
          `from decimal import Decimal
import sys
import pyarrow.parquet as pq
for path in sys.argv[1:]:
    rows=pq.read_table(path).to_pylist()
    assert len(rows)==3
    assert rows[0]['id']==9007199254740993
    assert rows[0]['amount']==Decimal('12.340')
    assert rows[0]['active'] is True
`,
          ...written,
        ],
        { encoding: "utf8", stdio: "pipe" },
      );

      for (const [action, suffix] of [
        ["schema-broken", "source"],
        ["schema-duplicate", "quality"],
      ]) {
        await control(action, record.kind);
        const id = record.kind + "-json-" + suffix;
        const failure = command("run", "--run-id", id);
        assert.equal(failure.ok, false);
        privateResult(failure);
        if (suffix === "quality")
          assert.equal(failure.diagnostics[0].code, "QUALITY_FAILED");
        assert.ok(
          !walk(resolve(root, "build/generated/data")).some((p) =>
            p.includes("/" + id + "/"),
          ),
        );
        await control("schema-repair", record.kind);
        passed(command("run", "--retry", id));
      }
      Object.assign(record, {
        sdkCliMcpParity: true,
        consentAndPermissionDenied: true,
        sampledMetadataRows: 2,
        byteLimit: 1048576,
        nullableNoGuessedKeys: true,
        durableDrafts: 2,
        exactInt64AndDecimal: true,
        committedParquetPrecision: true,
        nestedRequiresReview: true,
        malformedMetadataAtomic: true,
        snapshotCounts: { orders: 3, customers: 3 },
        sourceAndQualityAtomic: true,
        sameRunRetry: true,
      });
      console.log(
        record.kind +
          " installed remote JSON schema, reviewed quality and retry passed",
      );
    }
    for (const file of readdirSync(
      resolve(root, ".ingestron/source-access"),
    ).filter((f) => f.endsWith(".json")))
      assert.doesNotMatch(
        readFileSync(resolve(root, ".ingestron/source-access", file), "utf8"),
        /PRIVATE_JSON_RECORD|PRIVATE_BROKEN_JSON|PRIVATE_NESTED|synthetic-secret|"rows"|"settings"|ingestron-sample-/,
      );
    result = "passed";
  } finally {
    writeFileSync(
      config.proof,
      JSON.stringify(
        {
          ...config,
          apiVersion: "ingestron.remote-json-schema-acceptance/v1",
          result,
          limits:
            "Immutable installed v21/source/provider with explicit bounded JSON/JSONL schema suggestions. Remote downloads retain existing64MiB transport bounds; schema parsing1MiB and returned records<=50. Real local SFTP and socket-fenced cloud/Graph fixtures; no vendor qualification.",
        },
        null,
        2,
      ) + "\n",
    );
  }
}
