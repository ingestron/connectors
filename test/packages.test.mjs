import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { parse } from "yaml";
import { settings } from "../src/settings.mjs";
import { conforms, runtimeContract } from "../src/connection-contract.mjs";
const sha = (v) => createHash("sha256").update(v).digest("hex");
test("released source assets bind schema, code, requirements and licence to one digest", () => {
  for (const source of ["github"]) {
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
});
