/** Rebuild a standalone connector package from its owned runtime sources. */
import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
const root = fileURLToPath(new URL("../", import.meta.url));
const read = (name) => readFileSync(resolve(root, name), "utf8");
const hash = (data) => createHash("sha256").update(data).digest("hex");
const manifest = JSON.parse(read("connector.yaml"));
const source = JSON.parse(read("runtime-assets.json"));
const files = Object.fromEntries(
  Object.entries(source).map(([name, path]) => [name, read(path)]),
);
files["runtime.lock.json"] = JSON.stringify(
  {
    apiVersion: "ingestron.singer-runtime-lock/v1",
    connector: manifest.connector.split(":")[1],
    files: Object.fromEntries(
      Object.entries(files).map(([name, data]) => [name, hash(data)]),
    ),
  },
  null,
  2,
);
const content = JSON.stringify(files);
writeFileSync(resolve(root, manifest.runtime.path), content);
manifest.runtime.sha256 = hash(content);
writeFileSync(
  resolve(root, "connector.yaml"),
  JSON.stringify(manifest, null, 2) + "\n",
);
console.log(
  "Built locked " + manifest.id + "@" + manifest.version + " runtime",
);
