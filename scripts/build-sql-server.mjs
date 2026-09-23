import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { createHash } from "node:crypto";
import { stringify } from "yaml";
import { format } from "prettier";
import {
  sqlServerSettings,
  sqlServerTableSource,
} from "../src/sql-server-settings.mjs";
import {
  selectionSchema,
  runtimeContract,
} from "../src/connection-contract.mjs";

const sha = (v) => createHash("sha256").update(v).digest("hex");
const read = (p) => readFileSync(p, "utf8");
const dir = "connectors/sql-server";
const files = {
  "singer_runtime.py": read("runtime/sql_server_runtime.py"),
  "sql_server_reader.py": read("runtime/sql_server_reader.py"),
  "snapshot_runtime.py": read("runtime/singer_runtime.py"),
  "files_reader.py": read("runtime/files_reader.py"),
  "singer_bridge.py": read("runtime/singer_bridge.py"),
  "singer_inventory.py": read("runtime/singer_inventory.py"),
  "connectors.json": JSON.stringify([
    {
      id: "sql-server@1.15.0",
      package: "mssql-python",
      version: "1.15.0",
      licence: "MIT (Python driver); ODBC binary has separate Microsoft terms",
      executable: "sql-server",
      prepared: true,
      supportedStreams: [],
    },
  ]),
  "settings.schema.json": JSON.stringify(sqlServerSettings),
  "requirements.lock.txt": read("runtime/sql-server.lock"),
  "build-tools.lock.txt": read("runtime/build-tools.lock"),
  "UPSTREAM-LICENSE.txt": read("runtime/sql-server.license.txt"),
  "LICENSE.txt": read("LICENSE"),
  "RUNTIME-NOTICES.txt":
    "Original Ingestron adapter: Apache-2.0, Otrera Limited. mssql-python Python code is MIT. The installed mssql-python-odbc binary is distributed under separate Microsoft terms; inspect the installed distribution before use or redistribution. Python dependencies are installed separately.\n",
};
files["runtime.lock.json"] = JSON.stringify(
  {
    apiVersion: "ingestron.singer-runtime-lock/v1",
    connector: "sql-server@1.15.0",
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
  id: "sql-server",
  version: "1.1.0",
  description:
    "Reviewed local snapshots from multiple SQL Server or Azure SQL tables",
  connector: "singer:sql-server@1.15.0",
  documentation:
    "https://github.com/ingestron/connectors/blob/main/docs/sql-server.md",
  upstream: {
    ecosystem: "singer",
    variant: "ingestron",
    package: "mssql-python",
    version: "1.15.0",
    repository: "https://github.com/microsoft/mssql-python",
    licence: "MIT (driver); bundled ODBC binary under Microsoft terms",
    licenceFile: dir + "/UPSTREAM-LICENSE.txt",
    licenceStatus: "evidenced",
  },
  runtime: {
    path: dir + "/runtime.json",
    sha256: sha(content),
    contract: runtimeContract,
  },
  definition: {
    settingsSchema: sqlServerSettings,
    selectionSchema,
    tableSourceSchema: sqlServerTableSource,
  },
  execution: {
    local: {
      modes: ["local"],
      evidence:
        "Bounded read-only table snapshot; SQL password live Northwind qualification and synthetic authentication/negative-path checks",
    },
  },
};
writeFileSync(
  dir + "/connector.yaml",
  await format(stringify(manifest), { parser: "yaml" }),
);
