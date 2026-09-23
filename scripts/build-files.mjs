import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { createHash } from "node:crypto";
import { stringify } from "yaml";
import { format } from "prettier";
import { filesSettings, filesTableSource } from "../src/files-settings.mjs";
import {
  selectionSchema,
  runtimeContract,
} from "../src/connection-contract.mjs";
const sha = (v) => createHash("sha256").update(v).digest("hex");
const read = (p) => readFileSync(p, "utf8");
const files = {
  "singer_runtime.py": read("runtime/files_table_runtime.py"),
  "snapshot_runtime.py": read("runtime/singer_runtime.py"),
  "files_reader.py": read("runtime/files_reader.py"),
  "singer_bridge.py": read("runtime/singer_bridge.py"),
  "singer_inventory.py": read("runtime/singer_inventory.py"),
  "connectors.json": JSON.stringify([
    {
      id: "files@23.0.1",
      package: "pyarrow",
      version: "23.0.1",
      licence: "Apache-2.0",
      executable: "files",
      prepared: true,
      supportedStreams: ["records"],
    },
  ]),
  "settings.schema.json": JSON.stringify(filesSettings),
  "requirements.lock.txt": read("runtime/files.lock"),
  "build-tools.lock.txt": read("runtime/build-tools.lock"),
  "UPSTREAM-LICENSE.txt": read("runtime/files.license.txt"),
  "LICENSE.txt": read("LICENSE"),
  "UPSTREAM-NOTICE.txt": read("runtime/files.notice.txt"),
  "RUNTIME-NOTICES.txt":
    "Original Ingestron adapter: Apache-2.0, Otrera Limited. Apache Arrow retains its bundled upstream notices. Python dependencies are installed separately with their original licences.\n",
};
files["runtime.lock.json"] = JSON.stringify(
  {
    apiVersion: "ingestron.singer-runtime-lock/v1",
    connector: "files@23.0.1",
    files: Object.fromEntries(
      Object.entries(files).map(([k, v]) => [k, sha(v)]),
    ),
  },
  null,
  2,
);
const dir = "connectors/files";
mkdirSync(dir, { recursive: true });
const content = JSON.stringify(files);
writeFileSync(dir + "/runtime.json", content);
writeFileSync(dir + "/UPSTREAM-LICENSE.txt", files["UPSTREAM-LICENSE.txt"]);
const manifest = {
  apiVersion: "ingestron.connector/v1",
  id: "files",
  version: "1.1.0",
  description:
    "Reviewed snapshots from local CSV, TSV, JSON, JSONL and Parquet files",
  connector: "singer:files@23.0.1",
  documentation:
    "https://github.com/ingestron/connectors/blob/main/docs/files.md",
  upstream: {
    ecosystem: "singer",
    variant: "ingestron",
    package: "pyarrow",
    version: "23.0.1",
    repository: "https://github.com/apache/arrow",
    licence: "Apache-2.0",
    licenceFile: dir + "/UPSTREAM-LICENSE.txt",
    licenceStatus: "evidenced",
  },
  runtime: {
    path: dir + "/runtime.json",
    sha256: sha(content),
    contract: runtimeContract,
  },
  definition: {
    settingsSchema: filesSettings,
    selectionSchema,
    tableSourceSchema: filesTableSource,
  },
  execution: {
    local: {
      modes: ["local"],
      evidence:
        "Bounded local file snapshot; release qualification records format, review, rejection and retry checks",
    },
  },
};
writeFileSync(
  dir + "/connector.yaml",
  await format(stringify(manifest), { parser: "yaml" }),
);
