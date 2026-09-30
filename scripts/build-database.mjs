// PostgreSQL, MySQL and Oracle connectors on the connector kit (PB-064 phase 3).
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { createHash } from "node:crypto";
import { stringify } from "yaml";
import { format } from "prettier";
import {
  databaseSettings,
  databaseTableSource,
} from "../src/database-settings.mjs";
import {
  selectionSchema,
  runtimeContract,
  quality,
} from "../src/connection-contract.mjs";
import { sources } from "../src/sources.mjs";

const sha = (v) => createHash("sha256").update(v).digest("hex");
const read = (p) => readFileSync(p, "utf8");
const connectors = [
  {
    id: "postgresql",
    label: "PostgreSQL",
    package: "pg8000",
    version: "1.31.5",
    repository: "https://github.com/tlocke/pg8000",
    licence: "BSD-3-Clause",
  },
  {
    id: "mysql",
    label: "MySQL and MariaDB",
    package: "PyMySQL",
    version: "1.2.3",
    repository: "https://github.com/PyMySQL/PyMySQL",
    licence: "MIT",
  },
  {
    id: "oracle",
    label: "Oracle",
    package: "oracledb",
    version: "26.0.1",
    repository: "https://github.com/oracle/python-oracledb",
    licence: "UPL-1.0 OR Apache-2.0",
  },
];
for (const c of connectors) {
  const dir = "connectors/" + c.id;
  const runtimeId = `${c.id}@${c.version}`;
  const files = {
    "singer_runtime.py": read(`runtime/${c.id}_runtime.py`),
    "database_runtime.py": read("runtime/database_runtime.py"),
    "dbapi_reader.py": read("runtime/dbapi_reader.py"),
    "snapshot_runtime.py": read("runtime/singer_runtime.py"),
    "singer_bridge.py": read("runtime/singer_bridge.py"),
    "connector_kit.py": read("runtime/connector_kit.py"),
    "quality_rules.py": read("runtime/quality_rules.py"),
    "singer_inventory.py": read("runtime/singer_inventory.py"),
    "connectors.json": JSON.stringify([
      {
        id: runtimeId,
        package: c.package,
        version: c.version,
        licence: c.licence,
        executable: c.id,
        prepared: true,
        supportedStreams: [],
      },
    ]),
    "settings.schema.json": JSON.stringify(databaseSettings(c.id)),
    "requirements.lock.txt": read(`runtime/${c.id}.lock`),
    "build-tools.lock.txt": read("runtime/build-tools.lock"),
    "UPSTREAM-LICENSE.txt": read(`runtime/${c.id}.license.txt`),
    "LICENSE.txt": read("LICENSE"),
    "RUNTIME-NOTICES.txt": `Original Ingestron adapter: Apache-2.0, Otrera Limited. ${c.package} ${c.version} is ${c.licence}. Python dependencies are installed separately and keep their own licence files and notices.\n`,
  };
  files["runtime.lock.json"] = JSON.stringify(
    {
      apiVersion: "ingestron.singer-runtime-lock/v1",
      connector: runtimeId,
      files: Object.fromEntries(
        Object.entries(files).map(([k, v]) => [k, sha(v)]),
      ),
    },
    null,
    2,
  );
  mkdirSync(dir, { recursive: true });
  const content = JSON.stringify(files);
  writeFileSync(dir + "/runtime.json", content);
  writeFileSync(dir + "/UPSTREAM-LICENSE.txt", files["UPSTREAM-LICENSE.txt"]);
  const manifest = {
    apiVersion: "ingestron.connector/v1",
    id: c.id,
    version: "1.1.0",
    description: `Reviewed local snapshots from ${c.label} tables`,
    connector: `singer:${runtimeId}`,
    documentation: `https://github.com/ingestron/connectors/blob/main/docs/${c.id}.md`,
    upstream: {
      ecosystem: "singer",
      variant: "ingestron",
      package: c.package,
      version: c.version,
      repository: c.repository,
      licence: c.licence,
      licenceFile: dir + "/UPSTREAM-LICENSE.txt",
      licenceStatus: "evidenced",
    },
    runtime: {
      path: dir + "/runtime.json",
      sha256: sha(content),
      contract: runtimeContract,
    },
    quality,
    source: sources[c.id],
    definition: {
      settingsSchema: databaseSettings(c.id),
      selectionSchema,
      tableSourceSchema: databaseTableSource,
    },
    execution: {
      local: {
        modes: ["local"],
        evidence:
          "Bounded read-only table snapshot; conformance suite against synthetic fakes and local containers",
      },
    },
  };
  writeFileSync(
    dir + "/connector.yaml",
    await format(stringify(manifest), { parser: "yaml" }),
  );
}
