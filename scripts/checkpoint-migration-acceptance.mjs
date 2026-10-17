/** Installed source-owned checkpoint transition and real SDK append continuation. */
import assert from "node:assert/strict";
import {
  readFileSync,
  writeFileSync,
  readdirSync,
  cpSync,
  mkdirSync,
  mkdtempSync,
  realpathSync,
  existsSync,
  chmodSync,
  lstatSync,
} from "node:fs";
import { resolve, join, relative } from "node:path";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const options = {};
for (const name of [
  "CLI",
  "SOURCE_ORIGIN",
  "PROVIDER_ORIGIN",
  "FIXTURE_PROJECT",
  "OUTPUT",
  "PROOF",
])
  options[name] = resolve(
    assert.ok(process.env["INGESTRON_ACCEPTANCE_" + name]) ||
      process.env["INGESTRON_ACCEPTANCE_" + name],
  );
const cli = realpathSync(options.CLI);
const core = realpathSync(resolve(cli, "../@ingestron/core"));
const sdk = await import(pathToFileURL(join(core, "dist/sdk/index.js")).href);
const require = createRequire(join(cli, "package.json"));
const { parse, parseDocument } = require("yaml");
const sha = (path) =>
  createHash("sha256").update(readFileSync(path)).digest("hex");
const read = (path) => JSON.parse(readFileSync(path, "utf8"));
function inventory(root) {
  const entries = {};
  function walk(path) {
    for (const entry of readdirSync(path, { withFileTypes: true })) {
      const file = join(path, entry.name);
      assert.ok(
        !entry.isSymbolicLink(),
        "Unexpected link in checkpoint/build history",
      );
      if (entry.isDirectory()) walk(file);
      else {
        assert.ok(entry.isFile());
        entries[relative(root, file)] = sha(file);
      }
    }
  }
  walk(root);
  return entries;
}
const fixture = options.FIXTURE_PROJECT;
const from = "build/studio/dev/orders_append";
const studioDriver = process.env.INGESTRON_ACCEPTANCE_STUDIO_DRIVER;
const baseline = studioDriver
  ? "build/retained/dev/orders_append/default/before"
  : "build/checkpoint-baseline/orders_append";
const flow = "orders_append";
const originalData = join(fixture, from, "data", flow);
const original = {
  project: sha(join(fixture, "project.yaml")),
  lock: sha(join(fixture, "packages.lock.yaml")),
  data: inventory(originalData),
};
const fixtureProject = parse(
  readFileSync(join(fixture, "project.yaml"), "utf8"),
);
assert.equal(
  fixtureProject.connections.retail.settings.connection.host,
  "127.0.0.1",
);
assert.equal(fixtureProject.id, "postgres_incremental");
assert.ok(
  existsSync(join(fixture, ".local/source.env")),
  "Synthetic loopback credential file required",
);
mkdirSync(options.OUTPUT, { recursive: true });
const root = mkdtempSync(join(options.OUTPUT, "checkpoint-"));
const project = join(root, "project");
const checks = [];
const mode = process.env.INGESTRON_ACCEPTANCE_MODE ?? "source";
assert.ok(["source", "host"].includes(mode));
let result = "failed",
  prepared,
  migration,
  studio;
const record = (check, evidence = {}) => {
  checks.push({ check, ...evidence });
  console.log(JSON.stringify({ check, result: "passed" }));
};
function passed(value) {
  assert.equal(value.ok, true, JSON.stringify(value));
  return value.result;
}
const context = {
  root: project,
  environment: "dev",
  allowWrite: true,
  allowExecute: true,
  allowNetwork: false,
};
const operation = (name, input, authority = {}) =>
  sdk.executeAsync({ ...context, ...authority }, name, input);
const run = (args) =>
  operation("run", {
    ...(args.retry ? {} : { flow, from }),
    envFile: ".local/source.env",
    ...args,
  });
function invoke(python, args, cwd, expected = 0) {
  // Maintenance receives no source credentials; authenticated data calls use the SDK only.
  const child = spawnSync(python, args, {
    cwd,
    env: {
      PATH: process.env.PATH,
      LANG: "en_US.UTF-8",
      PYTHONNOUSERSITE: "1",
      PYTHONDONTWRITEBYTECODE: "1",
    },
    encoding: "utf8",
    timeout: 180000,
    maxBuffer: 2_000_000,
  });
  assert.equal(child.error, undefined);
  assert.equal(
    child.status,
    expected,
    "Source command returned an unexpected exit status",
  );
  try {
    return JSON.parse(child.stdout);
  } catch {
    assert.fail("Source command did not return bounded JSON");
  }
}
try {
  cpSync(fixture, project, {
    recursive: true,
    filter: (p) =>
      !["runs", "scheduler", "studio-jobs", "runtime-cache"].includes(
        p.split("/").at(-1),
      ),
  });
  chmodSync(join(project, ".local/source.env"), 0o600);
  if (studioDriver) {
    assert.equal(mode, "host");
    const { createHost } = await import(
      pathToFileURL(resolve(studioDriver)).href
    );
    studio = await createHost({ project, cli, flow, baseline, record });
  }
  if (process.env.INGESTRON_ACCEPTANCE_MODE === "host") {
    if (studio) await studio.retain();
    const retained = passed(
      await operation(
        studio ? "build_retained" : "build_retain",
        studio ? { directory: baseline } : { from, to: baseline },
        { allowExecute: false },
      ),
    );
    assert.equal(retained.apiVersion, "ingestron.retained-build/v1");
    assert.equal(retained.directory, baseline);
    assert.ok(retained.files > 0 && retained.bytes > 0);
    assert.match(retained.contentDigest, /^[a-f0-9]{64}$/);
    assert.deepEqual(
      inventory(join(project, baseline, "data", flow)),
      original.data,
    );
    const denied = await operation(
      "build_retain",
      { from, to: baseline },
      { allowExecute: false },
    );
    assert.equal(denied.ok, false);
    assert.equal(denied.diagnostics[0].code, "OWNER");
    const retainedByCli = spawnSync(
      process.execPath,
      [
        join(cli, "build/cli/cli/index.js"),
        "--project",
        project,
        "--environment",
        "dev",
        "--json",
        "--no-input",
        "checkpoint",
        "retain",
        "--from",
        from,
        "--to",
        "build/cli-baseline/orders_append",
      ],
      { cwd: project, encoding: "utf8", timeout: 180000 },
    );
    assert.equal(retainedByCli.error, undefined);
    assert.equal(retainedByCli.status, 0);
    assert.equal(
      passed(JSON.parse(retainedByCli.stdout)).contentDigest,
      retained.contentDigest,
    );
    record(
      "Actual installed SDK and CLI retain identical original managed build, review and data without source execution; existing destination is preserved",
      retained,
    );
  } else
    cpSync(join(project, from), join(project, baseline), { recursive: true });
  const baselineAssets = inventory(join(project, baseline, "flows", flow));
  const data = join(project, from, "data", flow);
  assert.deepEqual(inventory(data), original.data);
  const oldCommits = Object.keys(original.data).filter((p) =>
    p.endsWith("/commit.json"),
  );
  assert.equal(oldCommits.length, 1);
  const firstCommit = read(join(data, oldCommits[0]));
  assert.equal(firstCommit.state.sequence, 1);
  assert.deepEqual(firstCommit.state.bookmarks, { orders: "2" });
  const namespace = firstCommit.identity.namespace;
  const namespaceRoot = join(data, namespace);
  const origins = [
    {
      name: "provider",
      path: options.PROVIDER_ORIGIN,
      reference:
        "example/local/plugin/provider.yaml@" +
        read(options.PROVIDER_ORIGIN + "-evidence.json").version,
    },
    {
      name: "source",
      path: options.SOURCE_ORIGIN,
      reference:
        "example/sources/connectors/postgresql/connector.yaml@" +
        read(options.SOURCE_ORIGIN + "-evidence.json").sourceVersion,
    },
  ];
  const installed = [];
  for (const item of origins) {
    const evidence = read(item.path + "-evidence.json");
    assert.equal(evidence.result, "passed");
    for (const file of evidence.files)
      assert.equal(sha(join(item.path, file.path)), file.sha256);
    const location = ".ingestron/acceptance-origins/" + item.name;
    cpSync(item.path, join(project, location), { recursive: true });
    const selected = passed(
      await operation("packages_install", {
        reference: item.reference,
        fromGit: location,
      }),
    );
    assert.equal(selected.commit, evidence.commit);
    installed.push({ reference: item.reference, commit: selected.commit });
  }
  const providerProposal = passed(
    await operation("provider_migrate", {
      package: "local",
      to: origins[0].reference,
    }),
  );
  assert.deepEqual(
    providerProposal.changes.map((c) => c.path),
    ["project.yaml"],
  );
  passed(await operation("apply", { proposal: providerProposal }));
  const definition = parseDocument(
    readFileSync(join(project, "project.yaml"), "utf8"),
  );
  definition.setIn(["packages", "source"], origins[1].reference);
  const sourceProposal = passed(
    await operation("edit", {
      files: { "project.yaml": definition.toString() },
    }),
  );
  passed(await operation("apply", { proposal: sourceProposal }));
  passed(await operation("build", { flow, out: from }));
  assert.deepEqual(inventory(data), original.data);
  const currentFolder = join(project, from, "flows", flow);
  const previousFolder = join(project, baseline, "flows", flow);
  const currentConfig = join(currentFolder, "connector.json");
  const previousConfig = join(previousFolder, "connector.json");
  assert.notEqual(
    read(currentConfig).projectLock.specificationSha256,
    read(previousConfig).projectLock.specificationSha256,
  );
  record(
    "Actual installed upgrade and current build preserve every old commit and Parquet byte",
    { installed },
  );
  prepared = passed(
    await operation("runtime_prepare", { from, flow }, { allowNetwork: true }),
  );
  const environment = prepared.result.flows[0];
  assert.match(environment.environment, /^[a-f0-9]{64}$/);
  const python = environment.python;
  assert.equal(
    python,
    join(project, ".ingestron/runtimes", environment.environment, "bin/python"),
  );
  assert.ok(
    lstatSync(
      join(project, ".ingestron/runtimes", environment.environment),
    ).isDirectory(),
  );
  assert.equal(
    read(
      join(
        project,
        ".ingestron/runtimes",
        environment.environment,
        "ready.json",
      ),
    ).lock,
    environment.environment,
  );
  record("Actual SDK runtime preparation validates the locked environment", {
    environment: environment.environment,
    reused: environment.reused,
  });
  for (const action of ["discover", "review", "approve"])
    passed(await run({ action }));
  const runtime = join(currentFolder, "singer_runtime.py");
  const maintenanceArgs = (action) => [
    runtime,
    action,
    "--config",
    currentConfig,
    "--previous-config",
    previousConfig,
    "--output",
    data,
  ];
  const denied = invoke(
    python,
    [
      runtime,
      "run",
      "--config",
      currentConfig,
      "--output",
      data,
      "--run-id",
      "fresh-before-migration",
    ],
    currentFolder,
    1,
  );
  assert.equal(denied.errorCode, "CHECKPOINT_POLICY");
  assert.deepEqual(inventory(data), original.data);
  record(
    "Fresh current-source append denies old identity before source access; approved reviews were generated through the SDK",
  );
  const maintenance = async (action, expectedDigest, installedOnly = false) => {
    if (studio && !installedOnly)
      return studio.maintenance(action, expectedDigest);
    if (mode === "source")
      return invoke(
        python,
        [
          ...maintenanceArgs(action),
          ...(expectedDigest ? ["--expected-digest", expectedDigest] : []),
        ],
        currentFolder,
      );
    const operated = passed(
      await operation(action, {
        from,
        flow,
        previous: baseline,
        ...(expectedDigest ? { expectedDigest } : {}),
      }),
    );
    return {
      status: "Succeeded",
      migration: operated.result.flows[0].migration,
      runId: operated.id,
    };
  };
  const preview = await maintenance("checkpoint_preview");
  assert.equal(preview.status, "Succeeded");
  migration = preview.migration;
  assert.equal(migration.applied, false);
  assert.equal(migration.head.sequence, 1);
  assert.deepEqual(migration.head.bookmarks, { orders: "2" });
  assert.equal(migration.namespace, namespace);
  assert.match(migration.digest, /^[a-f0-9]{64}$/);
  assert.deepEqual(inventory(data), original.data);
  if (mode === "source") {
    const stale = invoke(
      python,
      [
        ...maintenanceArgs("checkpoint_apply"),
        "--expected-digest",
        "0".repeat(64),
      ],
      currentFolder,
      1,
    );
    assert.equal(stale.errorCode, "CHECKPOINT_MIGRATION_STALE");
  } else {
    const reviewFile = join(previousFolder, "review.json"),
      originalReview = readFileSync(reviewFile);
    try {
      writeFileSync(reviewFile, originalReview.toString("utf8") + " ");
      const modified = await operation("checkpoint_apply", {
        from,
        flow,
        previous: baseline,
        expectedDigest: migration.digest,
      });
      assert.equal(modified.ok, false);
      assert.equal(modified.diagnostics[0].code, "STALE");
      assert.deepEqual(inventory(data), original.data);
    } finally {
      writeFileSync(reviewFile, originalReview);
    }
    record(
      "Changing the retained approved review after preview refuses apply before provider dispatch and preserves committed data",
    );
    const denied = await operation("checkpoint_apply", {
      from,
      flow,
      previous: baseline,
      expectedDigest: "0".repeat(64),
    });
    assert.equal(denied.ok, false);
    assert.match(
      denied.diagnostics[0].message,
      /checkpoint head changed after review/i,
    );
    for (const previous of [
      from,
      "../outside",
      "build/checkpoint-baseline/customers_snapshot",
    ]) {
      const scoped = await operation("checkpoint_preview", {
        from,
        flow,
        previous,
      });
      assert.equal(scoped.ok, false);
    }
    const noAuthority = await operation(
      "checkpoint_preview",
      { from, flow, previous: baseline },
      { allowExecute: false },
    );
    assert.equal(noAuthority.ok, false);
    assert.equal(noAuthority.diagnostics[0].code, "PERMISSION");
    const cliPath = join(cli, "build/cli/cli/index.js");
    const operated = spawnSync(
      process.execPath,
      [
        cliPath,
        "--project",
        project,
        "--environment",
        "dev",
        "--json",
        "--no-input",
        "checkpoint",
        "preview",
        "--flow",
        flow,
        "--from",
        from,
        "--previous",
        baseline,
      ],
      { cwd: project, encoding: "utf8", timeout: 180000 },
    );
    assert.equal(operated.error, undefined);
    assert.equal(operated.status, 0);
    assert.equal(
      passed(JSON.parse(operated.stdout)).result.flows[0].migration.digest,
      migration.digest,
    );
    const { createServer } = await import(
      pathToFileURL(join(cli, "build/cli/mcp/index.js")).href
    );
    const { Client } = await import(
      pathToFileURL(
        require.resolve("@modelcontextprotocol/sdk/client/index.js"),
      ).href
    );
    const { InMemoryTransport } = await import(
      pathToFileURL(require.resolve("@modelcontextprotocol/sdk/inMemory.js"))
        .href
    );
    for (const authority of [false, true]) {
      const server = createServer(project, authority, "dev", false, authority),
        client = new Client({
          name: "checkpoint-acceptance",
          version: "1.0.0",
        }),
        [a, b] = InMemoryTransport.createLinkedPair();
      await server.connect(a);
      await client.connect(b);
      try {
        const names = (await client.listTools()).tools.map((tool) => tool.name);
        assert.equal(names.includes("ingestron_checkpoint_preview"), authority);
        assert.equal(names.includes("ingestron_checkpoint_apply"), authority);
        assert.equal(names.includes("ingestron_build_retain"), authority);
        if (authority) {
          const answer = await client.callTool({
            name: "ingestron_checkpoint_preview",
            arguments: { from, flow, previous: baseline },
          });
          assert.equal(
            passed(JSON.parse(answer.content[0].text)).result.flows[0].migration
              .digest,
            migration.digest,
          );
        }
      } finally {
        await client.close();
        await server.close();
      }
    }
    const writeOnlyServer = createServer(project, true, "dev", false, false),
      writeOnlyClient = new Client({
        name: "retention-write-only",
        version: "1.0.0",
      }),
      [writeA, writeB] = InMemoryTransport.createLinkedPair();
    await writeOnlyServer.connect(writeA);
    await writeOnlyClient.connect(writeB);
    try {
      const names = (await writeOnlyClient.listTools()).tools.map(
        (tool) => tool.name,
      );
      assert.ok(names.includes("ingestron_build_retain"));
      assert.ok(!names.includes("ingestron_checkpoint_apply"));
      const answer = await writeOnlyClient.callTool({
        name: "ingestron_build_retain",
        arguments: { from, to: "build/mcp-baseline/orders_append" },
      });
      const retained = passed(JSON.parse(answer.content[0].text));
      assert.equal(retained.apiVersion, "ingestron.retained-build/v1");
      assert.deepEqual(
        inventory(join(project, "build/mcp-baseline/orders_append/data", flow)),
        original.data,
      );
    } finally {
      await writeOnlyClient.close();
      await writeOnlyServer.close();
    }
    record(
      "Installed SDK, CLI and MCP agree on credential-free preview; readonly MCP omits maintenance and retention, write-only MCP retains data without execution authority, scope/permission denials preserve history",
    );
  }
  assert.deepEqual(inventory(data), original.data);
  const applied = await maintenance("checkpoint_apply", migration.digest);
  assert.equal(applied.status, "Succeeded");
  assert.equal(applied.migration.applied, true);
  assert.equal(applied.migration.digest, migration.digest);
  const journal = join(
    namespaceRoot,
    ".migrations",
    migration.digest + ".json",
  );
  assert.ok(existsSync(journal));
  const journalSha256 = sha(journal);
  for (const [file, digest] of Object.entries(original.data))
    assert.equal(sha(join(data, file)), digest);
  record(
    "Credential-free preview and exact-digest apply preserve the old cursor; stale review writes nothing",
    { migration, journalSha256 },
  );
  const first = passed(await run({ runId: "checkpoint-upgrade-batch-two" }));
  const second = passed(await run({ runId: "checkpoint-upgrade-batch-three" }));
  const empty = passed(await run({ runId: "checkpoint-upgrade-empty" }));
  const expected = [
    [first, 2, "4", 2],
    [second, 3, "5", 1],
    [empty, 4, "5", 0],
  ];
  for (const [batch, sequence, cursor, count] of expected) {
    assert.equal(batch.result.flows[0].checkpoint.sequence, sequence);
    assert.deepEqual(batch.result.flows[0].checkpoint.bookmarks, {
      orders: cursor,
    });
    assert.equal(batch.result.flows[0].tables[0].rows, count);
  }
  const inspection = invoke(
    python,
    [
      "-c",
      "import json,sys,pathlib,pyarrow.parquet as p; base=pathlib.Path(sys.argv[1]); runs=[]\nfor c in base.glob('*/commit.json'):\n r=json.loads(c.read_text()); ids=[v['id'] for f in c.parent.glob('*.parquet') for v in p.read_table(f).to_pylist()]; runs.append({'runId':c.parent.name,'sequence':r['state']['sequence'],'bookmarks':r['state']['bookmarks'],'parent':r['state']['parent'],'ids':ids})\nprint(json.dumps(sorted(runs,key=lambda r:r['sequence'])))",
      namespaceRoot,
    ],
    project,
  );
  assert.deepEqual(
    inspection.map((r) => r.ids),
    [[1, 2], [3, 4], [5], []],
  );
  assert.deepEqual(
    inspection.map((r) => r.sequence),
    [1, 2, 3, 4],
  );
  const committedBeforeRetry = inventory(data);
  const retry = passed(await run({ retry: first.id }));
  assert.equal(retry.id, first.id);
  assert.deepEqual(
    retry.result.flows[0].checkpoint,
    first.result.flows[0].checkpoint,
  );
  assert.deepEqual(inventory(data), committedBeforeRetry);
  if (studio) await studio.verifyAlreadyApplied(migration.digest);
  const reapplied = await maintenance(
    "checkpoint_apply",
    migration.digest,
    true,
  );
  if (mode === "host") {
    const recovered = passed(
      await operation("execution_recover", { id: applied.runId }),
    );
    assert.equal(recovered.acknowledgedOriginalOperation, true);
    assert.equal(recovered.result.flows[0].migration.digest, migration.digest);
    assert.equal(sha(journal), journalSha256);
  }
  assert.equal(reapplied.migration.digest, migration.digest);
  assert.deepEqual(reapplied.migration.head, migration.head);
  assert.equal(sha(journal), journalSha256);
  assert.deepEqual(inventory(data), committedBeforeRetry);
  const oldRetry = invoke(
    python,
    [
      join(previousFolder, "singer_runtime.py"),
      "run",
      "--config",
      previousConfig,
      "--output",
      data,
      "--run-id",
      firstCommit.identity.run_id,
    ],
    previousFolder,
  );
  assert.equal(oldRetry.status, "Succeeded");
  assert.equal(oldRetry.checkpoint.sequence, 1);
  assert.deepEqual(inventory(data), committedBeforeRetry);
  assert.deepEqual(inventory(previousFolder), baselineAssets);
  record(
    "Real SDK batches ingest IDs 3–4 then 5; empty batch and both old/new retries preserve committed history",
    { inspection, runIds: expected.map(([batch]) => batch.id) },
  );
  result = "passed";
} finally {
  if (studio) await studio.close();
  assert.equal(sha(join(fixture, "project.yaml")), original.project);
  assert.equal(sha(join(fixture, "packages.lock.yaml")), original.lock);
  assert.deepEqual(inventory(originalData), original.data);
  writeFileSync(
    options.PROOF,
    JSON.stringify(
      {
        result,
        root,
        project,
        coreVersion: sdk.version,
        checks,
        originalProjectUnchanged: true,
        scope: studioDriver
          ? "Actual immutable packaged shared Studio/editor host through installed CLI/core, locked provider/source and copied synthetic loopback PostgreSQL history. No browser interaction, vendor/cloud or migration-finaliser-death qualification."
          : mode === "host"
            ? "Actual installed SDK/CLI/MCP checkpoint preview/apply and original durable acknowledgement, immutable provider/source snapshots and real SDK append continuation on copied authorised loopback PostgreSQL history. No Studio/browser/cloud migration qualification."
            : "Actual immutable installed source maintenance CLI plus installed SDK/provider execution on a copied authorised synthetic loopback PostgreSQL history. No shared core/CLI/provider/Studio migration route, cloud or browser qualification claimed.",
      },
      null,
      2,
    ) + "\n",
  );
  console.log(JSON.stringify({ result, root, checks: checks.length }));
}
