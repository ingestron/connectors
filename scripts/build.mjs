import { createHash } from "node:crypto";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { stringify } from "yaml";
import { format } from "prettier";
import { settings } from "../src/settings.mjs";
import {
  selectionSchema,
  runtimeContract,
} from "../src/connection-contract.mjs";
const sha = (v) => createHash("sha256").update(v).digest("hex");
const singerFiles = [
  "singer_bridge.py",
  "github_tap.py",
  "singer_runtime.py",
  "singer_inventory.py",
  "connectors.json",
];
const singerCatalogue = JSON.parse(
  readFileSync("runtime/connectors.json", "utf8"),
);
const singerBundles = {};
for (const entry of singerCatalogue.filter((entry) => entry.prepared)) {
  const [name, version] = entry.id.split("@");
  const files = Object.fromEntries(
    singerFiles.map((name) => [name, readFileSync("runtime/" + name, "utf8")]),
  );
  files["settings.schema.json"] = JSON.stringify(
    settings[(entry.protocol ?? "singer") + ":" + entry.id],
  );
  files["build-tools.lock.txt"] = readFileSync(
    "runtime/build-tools.lock",
    "utf8",
  );
  files["requirements.lock.txt"] = readFileSync(
    "runtime/" + name + ".lock",
    "utf8",
  );
  files["UPSTREAM-LICENSE.txt"] = readFileSync(
    "runtime/" + name + ".license.txt",
    "utf8",
  );
  files["LICENSE.txt"] = readFileSync("LICENSE", "utf8");
  files["RUNTIME-NOTICES.txt"] = readFileSync("runtime/NOTICES.txt", "utf8");
  files["runtime.lock.json"] = JSON.stringify(
    {
      apiVersion: "ingestron.singer-runtime-lock/v1",
      connector: name + "@" + version,
      files: Object.fromEntries(
        Object.entries(files).map(([path, content]) => [path, sha(content)]),
      ),
    },
    null,
    2,
  );
  singerBundles[name + "@" + version] = files;
}

for (const entry of singerCatalogue.filter((e) => e.prepared)) {
  const name = entry.id.split("@")[0],
    ecosystem = entry.protocol ?? "singer";
  const folder = "connectors/" + name;
  mkdirSync(folder, { recursive: true });
  const files = singerBundles[entry.id],
    content = JSON.stringify(files);
  writeFileSync(folder + "/runtime.json", content);
  writeFileSync(
    folder + "/UPSTREAM-LICENSE.txt",
    readFileSync("runtime/" + name + ".license.txt"),
  );
  const manifest = {
    apiVersion: "ingestron.connector/v1",
    id: name,
    version: entry.packageVersion,
    description: name + " customer-operated full snapshot connector",
    connector: ecosystem + ":" + entry.id,
    documentation:
      "https://github.com/ingestron/connectors/blob/main/docs/github.md",
    upstream: {
      ecosystem,
      variant: "meltanolabs",
      package: entry.package,
      version: entry.version,
      repository: "https://github.com/MeltanoLabs/tap-github",
      licence: entry.licence,
      licenceFile: folder + "/UPSTREAM-LICENSE.txt",
      licenceStatus: "evidenced",
    },
    runtime: {
      path: folder + "/runtime.json",
      sha256: sha(content),
      contract: runtimeContract,
    },
    definition: {
      settingsSchema: settings[ecosystem + ":" + entry.id],
      selectionSchema,
    },
    execution: {
      local: {
        modes: ["local"],
        evidence:
          entry.evidence + "; local provider installed-package qualification",
      },
    },
  };
  writeFileSync(
    folder + "/connector.yaml",
    await format(stringify(JSON.parse(JSON.stringify(manifest))), {
      parser: "yaml",
    }),
  );
}

if (process.env.GITHUB_REF_TYPE === "tag") {
  const tag = process.env.GITHUB_REF_NAME;
  if (tag.startsWith("v")) {
    if (tag !== "v" + JSON.parse(readFileSync("package.json")).version)
      throw Error("Runtime tag mismatch");
  } else {
    const match = /^(github)-(\d+\.\d+\.\d+)$/.exec(tag);
    if (!match) throw Error("Unknown source tag");
    const { parse } = await import("yaml");
    if (
      parse(readFileSync(`connectors/${match[1]}/connector.yaml`, "utf8"))
        .version !== match[2]
    )
      throw Error("Source tag mismatch");
  }
}
