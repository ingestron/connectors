import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { parse } from "yaml";
import { settings } from "../src/settings.mjs";
import { conforms, runtimeContract } from "../src/connection-contract.mjs";
const sha = (v) => createHash("sha256").update(v).digest("hex");
test("released source assets bind schema, code, requirements and licence to one digest", () => {
  for (const source of ["github", "files", "azure-blob", "sql-server"]) {
    const m = parse(
      readFileSync(`connectors/${source}/connector.yaml`, "utf8"),
    );
    const text = readFileSync(m.runtime.path, "utf8"),
      files = JSON.parse(text),
      lock = JSON.parse(files["runtime.lock.json"]);
    assert.equal(m.runtime.sha256, sha(text));
    assert.equal(m.runtime.contract, runtimeContract);
    assert.equal(lock.connector, m.connector.split(":")[1]);
    assert.deepEqual(
      JSON.parse(files["settings.schema.json"]),
      m.definition.settingsSchema,
    );
    for (const [path, digest] of Object.entries(lock.files))
      assert.equal(sha(files[path]), digest, path);
    assert.equal(
      files["UPSTREAM-LICENSE.txt"],
      readFileSync(m.upstream.licenceFile, "utf8"),
    );
    assert.ok(files["requirements.lock.txt"].includes("--hash=sha256:"));
  }
});
test("source-owned bounds and credential references reject invalid configuration", () => {
  assert.equal(
    conforms(settings["singer:github@1.29.2"], {
      auth_token: "plaintext",
      repositories: ["demo/repo"],
    }),
    false,
  );
  const sql = parse(
    readFileSync("connectors/sql-server/connector.yaml", "utf8"),
  );
  const base = {
    object: { schema: "dbo", table: "Products" },
    connection: {
      server: "example.database.windows.net",
      database: "northwind",
      authentication: {
        method: "sql-password",
        username: "reader",
        password: { $secret: { env: "SQL_READER_PASSWORD" } },
      },
    },
  };
  assert.equal(conforms(sql.definition.settingsSchema, base), true);
  assert.equal(
    conforms(sql.definition.settingsSchema, {
      ...base,
      connection: {
        ...base.connection,
        authentication: {
          method: "sql-password",
          username: "reader",
          password: "plaintext",
        },
      },
    }),
    false,
  );
  for (const authentication of [
    { method: "entra-default" },
    { method: "entra-managed-identity" },
    {
      method: "entra-service-principal",
      client_id: "id",
      client_secret: { $secret: { env: "SQL_CLIENT_SECRET" } },
    },
  ]) {
    assert.equal(
      conforms(sql.definition.settingsSchema, {
        ...base,
        connection: { ...base.connection, authentication },
      }),
      true,
    );
  }
});

test("official catalogue contains only qualified exact releases and stable identities", () => {
  const c = JSON.parse(readFileSync("catalogue.json", "utf8"));
  assert.equal(c.apiVersion, "ingestron.catalogue/v1");
  assert.deepEqual(Object.keys(c.plugins).sort(), [
    "azure-blob",
    "files",
    "github",
    "local",
    "sql-server",
  ]);
  assert.equal(c.plugins.github.repository, "ingestron/connectors");
  assert.equal(c.plugins.github.path, "connectors/github/connector.yaml");
  assert.equal(c.plugins.github.tagPrefix, "github-");
  assert.equal(c.plugins.local.repository, "ingestron/provider-local");
  assert.equal(c.plugins.local.path, "plugin/provider.yaml");
  assert.equal(c.plugins.local.tagPrefix, "");
  for (const p of Object.values(c.plugins)) {
    assert.ok(
      p.releases.at(-1).coreVersions.includes("0.12.2"),
      "Every latest official shortcut must be qualified with the current core",
    );
    assert.equal(
      new Set(p.releases.map((r) => r.version)).size,
      p.releases.length,
    );
    for (const r of p.releases) {
      assert.match(r.version, /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/);
      assert.ok(r.coreVersions.length);
      for (const v of r.coreVersions) assert.match(v, /^\d+\.\d+\.\d+$/);
    }
  }
});

test("the entire Git package tree satisfies the current text-only host boundary", () => {
  const names = execFileSync(
    "git",
    ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
    { encoding: "utf8" },
  )
    .split("\0")
    .filter(Boolean);
  let total = 0;
  for (const name of new Set(names)) {
    if (!existsSync(name)) continue;
    const bytes = readFileSync(name);
    total += bytes.length;
    assert.ok(!bytes.includes(0), name);
    assert.equal(
      Buffer.from(new TextDecoder("utf-8", { fatal: true }).decode(bytes))
        .length,
      bytes.length,
      name,
    );
    assert.ok(bytes.length <= 2 * 1024 * 1024, name);
  }
  assert.ok(names.length <= 1024);
  assert.ok(total <= 10 * 1024 * 1024);
});
