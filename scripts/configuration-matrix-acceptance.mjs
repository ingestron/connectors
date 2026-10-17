/** All declared source settings through immutable installed clients; no source reads. */
import assert from "node:assert/strict";
import {
  cpSync,
  readFileSync,
  writeFileSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  realpathSync,
} from "node:fs";
import { resolve, dirname } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import { execFileSync, spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { createHash, randomUUID } from "node:crypto";
for (const key of [
  "INGESTRON_ACCEPTANCE_CLI_PACKAGE",
  "INGESTRON_ACCEPTANCE_PROVIDER",
  "INGESTRON_ACCEPTANCE_OUTPUT",
  "INGESTRON_ACCEPTANCE_PROOF",
])
  assert.ok(process.env[key], "Set " + key);
const owner = resolve(dirname(fileURLToPath(import.meta.url)), ".."),
  cliRoot = realpathSync(process.env.INGESTRON_ACCEPTANCE_CLI_PACKAGE),
  coreRoot = realpathSync(resolve(cliRoot, "../@ingestron/core")),
  cli = resolve(cliRoot, "build/cli/cli/index.js"),
  base = resolve(process.env.INGESTRON_ACCEPTANCE_OUTPUT),
  proof = resolve(process.env.INGESTRON_ACCEPTANCE_PROOF),
  provider = resolve(process.env.INGESTRON_ACCEPTANCE_PROVIDER);
const require = createRequire(resolve(cliRoot, "package.json")),
  { parse, stringify } = require("yaml");
const sdk = await import(
    pathToFileURL(resolve(coreRoot, "dist/sdk/adapter.js")).href
  ),
  { execute, executeAsync } = await import(
    pathToFileURL(resolve(coreRoot, "dist/sdk/index.js")).href
  );
const { Client } = await import(
    pathToFileURL(require.resolve("@modelcontextprotocol/sdk/client/index.js"))
      .href
  ),
  { StdioClientTransport } = await import(
    pathToFileURL(require.resolve("@modelcontextprotocol/sdk/client/stdio.js"))
      .href
  );
assert.equal(
  JSON.parse(readFileSync(resolve(coreRoot, "package.json"), "utf8")).version,
  "0.12.15",
);
assert.equal(
  JSON.parse(readFileSync(resolve(cliRoot, "package.json"), "utf8")).version,
  "0.17.9",
);
mkdirSync(base, { recursive: true });
const root = mkdtempSync(resolve(base, "source-matrix-")),
  snapshot = mkdtempSync(resolve(base, "source-snapshot-")),
  providerSnapshot = mkdtempSync(resolve(base, "provider-snapshot-"));
const ids = readdirSync(resolve(owner, "connectors"), { withFileTypes: true })
  .filter((e) => e.isDirectory() && /^[a-z][a-z0-9-]*$/.test(e.name))
  .map((e) => e.name)
  .sort();
assert.equal(ids.length, 16);
for (const id of ids)
  cpSync(
    resolve(owner, "connectors", id),
    resolve(snapshot, "connectors", id),
    { recursive: true },
  );
cpSync(resolve(provider, "plugin"), resolve(providerSnapshot, "plugin"), {
  recursive: true,
  filter: (p) => !p.includes("__pycache__"),
});
const git = (cwd, ...args) =>
  execFileSync("git", args, { cwd, encoding: "utf8", stdio: "pipe" });
for (const directory of [snapshot, providerSnapshot]) {
  git(directory, "init", "-q");
  git(directory, "add", ".");
  git(
    directory,
    "-c",
    "user.name=Fixture",
    "-c",
    "user.email=fixture@example.invalid",
    "commit",
    "-qm",
    "Immutable synthetic source configuration matrix",
  );
}
const providerManifest = parse(
  readFileSync(resolve(providerSnapshot, "plugin/provider.yaml"), "utf8"),
);
assert.equal(providerManifest.version, "0.4.9");
git(providerSnapshot, "tag", providerManifest.version);
const providerReference =
  "example/local/plugin/provider.yaml@" + providerManifest.version;
sdk.installPackage(root, providerReference, { fromGit: providerSnapshot });
const secret = (id) => ({
    $secret: {
      env:
        "INGESTRON_MATRIX_MISSING_" +
        id.toUpperCase().replaceAll("-", "_") +
        "_" +
        suffix,
    },
  }),
  suffix = randomUUID().replaceAll("-", "").toUpperCase();
const graph = {
  tenant_id: "11111111-1111-4111-8111-111111111111",
  client_id: "22222222-2222-4222-8222-222222222222",
};
const db = (id) => ({
  connection: {
    host: "db.example.invalid",
    ...(id === "oracle" ? { service: "retail" } : { database: "retail" }),
    user: "reader",
    password: secret(id),
    tls: "require",
  },
});
const cases = {
  "azure-blob": {
    settings: {
      account: "retaildemo",
      container: "bronze",
      sas_token: secret("azure-blob"),
    },
    source: { path: "orders.csv", format: "csv" },
  },
  files: {
    settings: {},
    source: { path: resolve(root, "synthetic.csv"), format: "csv" },
  },
  gcs: {
    settings: {
      bucket: "bronze",
      access_key_id: "synthetic-hmac-id",
      secret_access_key: secret("gcs"),
    },
    source: { path: "orders.csv", format: "csv" },
  },
  github: {
    settings: {
      authentication: "token",
      repositories: ["example/retail"],
      auth_token: secret("github"),
    },
    source: { stream: "issues" },
  },
  hubspot: {
    settings: { access_token: secret("hubspot") },
    source: { object: "contacts" },
  },
  jira: {
    settings: {
      site: "https://retail.atlassian.net",
      email: "reader@example.invalid",
      api_token: secret("jira"),
    },
    source: { object: "issues", jql: "project = RETAIL" },
  },
  mysql: {
    settings: db("mysql"),
    source: { schema: "retail", table: "orders" },
  },
  onedrive: {
    settings: {
      ...graph,
      client_secret: secret("onedrive"),
      user: "reader@example.invalid",
    },
    source: { path: "orders.csv", format: "csv" },
  },
  oracle: {
    settings: db("oracle"),
    source: { schema: "RETAIL", table: "ORDERS" },
  },
  postgresql: {
    settings: db("postgresql"),
    source: { schema: "public", table: "orders" },
  },
  s3: {
    settings: {
      bucket: "bronze",
      region: "us-east-1",
      access_key_id: "synthetic-key-id",
      secret_access_key: secret("s3"),
    },
    source: { path: "orders.csv", format: "csv" },
  },
  salesforce: {
    settings: {
      instance_url: "https://retail.my.salesforce.com",
      client_id: "synthetic-client",
      client_secret: secret("salesforce"),
    },
    source: { object: "Account" },
  },
  sftp: {
    settings: {
      host: "sftp.example.invalid",
      user: "reader",
      private_key: secret("sftp"),
      host_key: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAISyntheticHostKey",
    },
    source: { path: "orders.csv", format: "csv" },
  },
  sharepoint: {
    settings: {
      ...graph,
      client_secret: secret("sharepoint"),
      site: "https://retail.sharepoint.com/sites/finance",
    },
    source: {
      path: "Shared Documents/orders.csv",
      format: "csv",
      entity: "file",
    },
  },
  "sql-server": {
    settings: {
      connection: {
        server: "db.example.invalid",
        database: "retail",
        authentication: {
          method: "sql-password",
          username: "reader",
          password: secret("sql-server"),
        },
      },
    },
    source: { schema: "dbo", table: "Orders" },
  },
  stripe: {
    settings: { api_key: secret("stripe") },
    source: { object: "customers" },
  },
};
assert.deepEqual(Object.keys(cases).sort(), ids);
const manifests = {},
  references = {},
  packages = { local: providerReference },
  connections = {},
  flows = [];
for (const id of ids) {
  const m = parse(
    readFileSync(resolve(snapshot, "connectors", id, "connector.yaml"), "utf8"),
  );
  manifests[id] = m;
  git(snapshot, "tag", id + "-" + m.version);
  const ref =
    "example/sources/connectors/" + id + "/connector.yaml@" + m.version;
  references[id] = ref;
  sdk.installPackage(root, ref, { fromGit: snapshot, tagPrefix: id + "-" });
  packages[id] = ref;
  connections[id] = {
    package: id,
    sourceId: id,
    tenantId: "synthetic",
    settings: cases[id].settings,
  };
  flows.push({
    apiVersion: "ingestron.flow/v1",
    id: "flow_" + id.replaceAll("-", "_"),
    kind: "ingestion",
    provider: "local",
    ingestion: { connection: id, execution: { mode: "local" } },
    tables: {
      orders: {
        source: cases[id].source,
        contract: {
          apiVersion: "v3.1.0",
          kind: "DataContract",
          id: "contract_" + id,
          name: "orders",
          version: "1.0.0",
          status: "draft",
          schema: [
            {
              name: "orders",
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
                },
              ],
            },
          ],
        },
      },
    },
  });
}
const project = {
  apiVersion: "ingestron.project/v1",
  id: "source_configuration_matrix",
  packages,
  providers: {
    configurations: { local: { package: "local", binding: "runtime" } },
  },
  defaults: { provider: "local" },
  environments: Object.fromEntries(
    ["dev", "test"].map((environment) => [
      environment,
      {
        apiVersion: "ingestron.environment/v1",
        environment,
        bindings: { runtime: { kind: "local" } },
        values: {},
      },
    ]),
  ),
  connections,
  flows,
};
const projectPath = resolve(root, "project.yaml"),
  put = () => writeFileSync(projectPath, stringify(project));
put();
const original = readFileSync(projectPath, "utf8"),
  context = {
    root,
    environment: "dev",
    allowWrite: true,
    allowExecute: false,
    allowNetwork: false,
  },
  records = [],
  checks = [];
const command = (
  operation,
  args = {},
  permissions = [],
  environment = "dev",
) => {
  const r = spawnSync(
    process.execPath,
    [
      cli,
      "--project",
      root,
      "--env",
      environment,
      "--json",
      "--no-input",
      "operation",
      operation,
      ...permissions,
    ],
    {
      input: JSON.stringify(args),
      encoding: "utf8",
      timeout: 120000,
      maxBuffer: 2 * 1024 * 1024,
    },
  );
  assert.equal(r.error, undefined);
  return JSON.parse(r.stdout);
};
const access = (id) =>
  executeAsync(context, "connection_access", { connection: id });
const fails = (value, pattern) => {
  assert.equal(value.ok, false, JSON.stringify(value));
  assert.match(JSON.stringify(value.diagnostics), pattern);
};
const client = new Client({
  name: "source-configuration-matrix",
  version: "1.0.0",
});
let result = "failed";
try {
  await client.connect(
    new StdioClientTransport({
      command: process.execPath,
      args: [cli, "--project", root, "advanced", "mcp", "serve"],
      stderr: "pipe",
    }),
  );
  const tools = await client.listTools();
  assert.ok(tools.tools.some((t) => t.name === "ingestron_connection_access"));
  assert.ok(!tools.tools.some((t) => t.name === "ingestron_connection_test"));
  assert.ok(!tools.tools.some((t) => t.name === "ingestron_connection_sample"));
  for (const id of ids) {
    const direct = await access(id);
    assert.equal(direct.ok, true, JSON.stringify(direct));
    assert.deepEqual(direct.result.actions, manifests[id].sourceAccess.actions);
    assert.equal(direct.result.executor, providerReference);
    assert.ok(/^[a-f0-9]{64}$/.test(direct.result.fingerprint));
    assert.equal(direct.result.reason, undefined);
    const viaCli = command("connection_access", { connection: id });
    assert.equal(viaCli.ok, true, JSON.stringify(viaCli));
    assert.deepEqual(viaCli.result, JSON.parse(JSON.stringify(direct.result)));
    const viaMcp = JSON.parse(
      (
        await client.callTool({
          name: "ingestron_connection_access",
          arguments: { connection: id },
        })
      ).content[0].text,
    );
    assert.equal(viaMcp.ok, true, JSON.stringify(viaMcp));
    assert.deepEqual(viaMcp.result, JSON.parse(JSON.stringify(direct.result)));
    const checked = execute(context, "connection_prepare", {
      flow: "flow_" + id.replaceAll("-", "_"),
      validateOnly: true,
    });
    assert.equal(checked.ok, true, JSON.stringify(checked.diagnostics));
    const other = await executeAsync(
      { ...context, environment: "test" },
      "connection_access",
      { connection: id },
    );
    assert.equal(other.ok, true);
    assert.notEqual(other.result.fingerprint, direct.result.fingerprint);
    const saved = project.connections[id].settings;
    project.connections[id].settings = {
      ...saved,
      unrecognised: "matrix-private-value",
    };
    put();
    const invalid = await access(id);
    fails(invalid, /CONNECTION/);
    assert.doesNotMatch(JSON.stringify(invalid), /matrix-private-value/);
    fails(command("connection_access", { connection: id }), /CONNECTION/);
    project.connections[id].settings = saved;
    put();
    assert.equal(
      (await access(id)).result.fingerprint,
      direct.result.fingerprint,
    );
    const denial = await executeAsync(context, "connection_test", {
      connection: id,
      source: cases[id].source,
    });
    fails(denial, /PERMISSION/);
    let missing;
    if (id !== "files") {
      const names = JSON.stringify(saved).match(
        /INGESTRON_MATRIX_MISSING_[A-Z0-9_]+/g,
      );
      assert.ok(names?.length);
      for (const name of names) assert.equal(process.env[name], undefined);
      missing = await executeAsync(
        { ...context, allowExecute: true },
        "connection_test",
        { connection: id, source: cases[id].source },
      );
      fails(missing, /SECRET/);
      assert.match(JSON.stringify(missing), /Missing runtime secret/);
      assert.doesNotMatch(
        JSON.stringify(missing),
        /password value|matrix-private-value/,
      );
    }
    records.push({
      id,
      reference: references[id],
      version: manifests[id].version,
      runtimeSha256: manifests[id].runtime.sha256,
      actions: direct.result.actions,
      fingerprint: direct.result.fingerprint,
      prepared: true,
      unknownSettingsDenied: true,
      executionDenied: true,
      missingCredentialDenied: id !== "files",
    });
  }
  checks.push(
    "All sixteen independent immutable source releases expose the same settings-derived fingerprint/actions/executor through SDK, CLI and read-only MCP",
  );
  checks.push(
    "All sixteen reviewed source/table/contract definitions prepare offline without source records or executing a runtime",
  );
  checks.push(
    "Every source rejects unknown settings with value-free diagnostics, distinguishes environments and restores its exact fingerprint after correction",
  );
  checks.push(
    "All sixteen source tests require execution authority; fifteen credential methods fail with named missing-secret guidance before launching a source runtime",
  );
  const baseSql = project.connections["sql-server"].settings;
  for (const authentication of [
    { method: "entra-default" },
    { method: "entra-managed-identity", client_id: "synthetic-client" },
    {
      method: "entra-service-principal",
      client_id: "synthetic-client",
      client_secret: secret("sql-sp"),
    },
  ]) {
    project.connections["sql-server"].settings = {
      connection: { ...baseSql.connection, authentication },
    };
    put();
    assert.equal((await access("sql-server")).ok, true);
    assert.equal(
      execute(context, "connection_prepare", {
        flow: "flow_sql_server",
        validateOnly: true,
      }).ok,
      true,
    );
  }
  project.connections["sql-server"].settings = baseSql;
  const baseGithub = project.connections.github.settings;
  project.connections.github.settings = {
    authentication: "anonymous",
    repositories: ["example/retail"],
  };
  put();
  assert.equal((await access("github")).ok, true);
  project.connections.github.settings = baseGithub;
  put();
  checks.push(
    "GitHub anonymous/token and all four SQL Server authentication shapes remain source-owned and pass installed offline settings checks",
  );
  const saved = project.connections.postgresql.settings;
  for (const settings of [
    { connection: { ...saved.connection, port: "5432" } },
    { connection: { ...saved.connection, port: 65536 } },
    { connection: { ...saved.connection, password: "matrix-private-value" } },
    {
      connection: {
        ...saved.connection,
        password: { $env: "MATRIX_PRIVATE_VALUE" },
      },
    },
  ]) {
    project.connections.postgresql.settings = settings;
    put();
    const invalid = await access("postgresql");
    fails(invalid, /CONNECTION|SECRET/);
    assert.doesNotMatch(JSON.stringify(invalid), /matrix-private-value/);
  }
  project.connections.postgresql.settings = saved;
  put();
  checks.push(
    "Wrong port types/ranges, plaintext passwords and compiler environment interpolation are rejected before source runtime access",
  );
  const native = project.connections.mysql;
  project.connections.mysql = { ...native, route: "native", kind: "mysql" };
  put();
  const value = await access("mysql");
  assert.equal(value.ok, true, JSON.stringify(value));
  assert.deepEqual(value.result.actions, []);
  assert.match(value.result.reason, /platform.*adapter|imported metadata/);
  project.connections.mysql = native;
  put();
  assert.equal(readFileSync(projectPath, "utf8"), original);
  const receipts = resolve(root, ".ingestron/source-access");
  if (readdirSync(resolve(root, ".ingestron")).includes("source-access"))
    for (const path of readdirSync(receipts).filter((p) =>
      p.endsWith(".json"),
    )) {
      const body = JSON.parse(readFileSync(resolve(receipts, path), "utf8"));
      assert.equal(body.status, "failed");
      assert.ok(body.result === undefined);
      assert.doesNotMatch(
        JSON.stringify(body),
        /matrix-private-value|auth_token|private_key|sas_token|client_secret|password/,
      );
    }
  checks.push(
    "Native-route access reports its missing platform adapter honestly; all private failure receipts contain no settings, credentials, records or successful execution",
  );
  result = "passed";
} finally {
  writeFileSync(projectPath, original);
  await client.close();
  writeFileSync(
    proof,
    JSON.stringify(
      {
        apiVersion: "ingestron.source-configuration-matrix-acceptance/v1",
        result,
        root,
        cli,
        core: "0.12.15",
        cliVersion: "0.17.9",
        sourceSnapshot: snapshot,
        sourceCommit: git(snapshot, "rev-parse", "HEAD").trim(),
        providerSnapshot,
        providerReference,
        providerCommit: git(providerSnapshot, "rev-parse", "HEAD").trim(),
        providerSourceAccessSha256: createHash("sha256")
          .update(
            readFileSync(
              resolve(
                providerSnapshot,
                "plugin/" + providerManifest.sourceAccess.entryPoint,
              ),
            ),
          )
          .digest("hex"),
        records,
        checks,
        limits: [
          "Installed configuration, static preparation, permission and pre-launch credential diagnostics only",
          "No source process launched, vendor traffic, samples, native accounts or snapshot/quality/runtime recovery qualification",
        ],
      },
      null,
      2,
    ) + "\n",
  );
}
console.log(
  JSON.stringify({
    result,
    sources: records.length,
    checks: checks.length,
    root,
  }),
);
