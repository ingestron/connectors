// Source-owned access methods are built into new candidate package versions.
import { readFileSync, writeFileSync, readdirSync } from "node:fs";
import { createHash } from "node:crypto";
import { parse, stringify } from "yaml";
import { format } from "prettier";
import { selectionSchema } from "../src/connection-contract.mjs";
const candidateVersions = {
  "azure-blob": "2.1.11",
  files: "1.5.14",
  gcs: "0.1.10",
  github: "1.36.10",
  hubspot: "0.1.8",
  jira: "0.1.8",
  mysql: "1.1.9",
  onedrive: "0.1.11",
  oracle: "1.1.9",
  postgresql: "1.1.10",
  s3: "1.0.10",
  salesforce: "0.1.8",
  sftp: "1.0.11",
  sharepoint: "0.1.11",
  "sql-server": "1.5.12",
  stripe: "0.1.8",
};
const jsonSchemaOptions = {
  type: "object",
  description:
    "Explicitly read JSON/JSONL records to suggest a draft schema. Samples do not prove required fields, keys or full-file validity. No record values are saved in discovery receipts.",
  properties: {
    sampleRecords: {
      type: "boolean",
      enum: [true],
      title: "Sample JSON records",
    },
    limit: {
      type: "integer",
      minimum: 1,
      maximum: 50,
      default: 20,
      title: "Record limit",
    },
  },
  required: ["sampleRecords"],
  additionalProperties: false,
};
const hash = (s) => createHash("sha256").update(s).digest("hex");
for (const id of readdirSync("connectors").filter((id) =>
  /^[a-z][a-z0-9-]*$/.test(id),
)) {
  const path = `connectors/${id}/connector.yaml`;
  const manifest = parse(readFileSync(path, "utf8"));
  const files = JSON.parse(readFileSync(manifest.runtime.path, "utf8"));
  const folderSource = ["sftp", "sharepoint", "onedrive"].includes(id);
  if (folderSource)
    files["folder_access.py"] = readFileSync(
      "runtime/folder_access.py",
      "utf8",
    );
  if (id === "sftp")
    files["sftp_reader.py"] = readFileSync("runtime/sftp_reader.py", "utf8");
  if (["sharepoint", "onedrive"].includes(id))
    files["graph_reader.py"] = readFileSync("runtime/graph_reader.py", "utf8");
  const cloudFiles = ["s3", "gcs", "azure-blob"].includes(id);
  if (cloudFiles)
    files["remote_file_access.py"] = readFileSync(
      "runtime/remote_file_access.py",
      "utf8",
    );
  const remoteSchema = folderSource || cloudFiles;
  if (remoteSchema) {
    files["remote_file_schema.py"] = readFileSync(
      "runtime/remote_file_schema.py",
      "utf8",
    );
    files["files_schema_sample.py"] = readFileSync(
      "runtime/files_schema_sample.py",
      "utf8",
    );
  }
  files["source_sample.py"] = readFileSync("runtime/source_sample.py", "utf8");
  files["source_access.py"] = readFileSync("runtime/source_access.py", "utf8");
  if (id === "files") {
    files["files_access.py"] = readFileSync("runtime/files_access.py", "utf8");
    files["files_data_sample.py"] = readFileSync(
      "runtime/files_data_sample.py",
      "utf8",
    );
    files["files_schema_sample.py"] = readFileSync(
      "runtime/files_schema_sample.py",
      "utf8",
    );
  }
  files["temporal_types.py"] = readFileSync(
    "runtime/temporal_types.py",
    "utf8",
  );
  files["quality_rules.py"] = readFileSync("runtime/quality_rules.py", "utf8");
  files["singer_bridge.py"] = readFileSync("runtime/singer_bridge.py", "utf8");
  files["metadata_documents.py"] = readFileSync(
    "runtime/metadata_documents.py",
    "utf8",
  );
  if (files["snapshot_runtime.py"] !== undefined)
    files["snapshot_runtime.py"] = readFileSync(
      "runtime/singer_runtime.py",
      "utf8",
    );
  else if (id === "github")
    files["singer_runtime.py"] = readFileSync(
      "runtime/singer_runtime.py",
      "utf8",
    );
  if (files["files_reader.py"] !== undefined)
    files["files_reader.py"] = readFileSync("runtime/files_reader.py", "utf8");
  for (const module of ["dbapi_reader.py", "sql_server_reader.py"])
    if (files[module] !== undefined)
      files[module] = readFileSync(`runtime/${module}`, "utf8");
  manifest.definition.selectionSchema = selectionSchema;
  const lock = JSON.parse(files["runtime.lock.json"]);
  if (id === "postgresql")
    lock.checkpointMigration = {
      apiVersion: "ingestron.checkpoint-migration/v1",
      strategy: "preserve-cursor-runtime-upgrade",
    };
  lock.files = Object.fromEntries(
    Object.entries(files)
      .filter(([name]) => name !== "runtime.lock.json")
      .map(([name, value]) => [name, hash(value)]),
  );
  files["runtime.lock.json"] = JSON.stringify(lock, null, 2);
  const content = JSON.stringify(files);
  writeFileSync(manifest.runtime.path, content);
  manifest.runtime.sha256 = hash(content);
  manifest.version = candidateVersions[id];
  manifest.sourceAccess = {
    apiVersion: "ingestron.source-access/v1",
    entryPoint:
      id === "files"
        ? "files_access.py"
        : folderSource
          ? "folder_access.py"
          : cloudFiles
            ? "remote_file_access.py"
            : "source_access.py",
    ...(folderSource
      ? {
          inventoryScopeSchema: {
            type: "object",
            properties: {
              directory: {
                type: "string",
                ...(id === "sftp" ? { minLength: 1 } : {}),
                maxLength: 1024,
                title: id === "sharepoint" ? "Library / folder" : "Folder",
                description:
                  id === "sharepoint"
                    ? "For files, include the library, such as Shared Documents/retail. Leave blank when browsing lists."
                    : id === "sftp"
                      ? "One literal remote folder. Wildcards are unavailable."
                      : "Leave blank for the drive root, or enter one relative folder.",
              },
              format: {
                type: "string",
                enum: ["all", "csv", "tsv", "json", "jsonl", "parquet"],
                title: "File format",
              },
              ...(id === "sharepoint"
                ? {
                    entity: {
                      type: "string",
                      enum: ["file", "list"],
                      title: "Object type",
                      default: "file",
                    },
                  }
                : {}),
            },
            ...(id === "sftp" ? { required: ["directory"] } : {}),
            additionalProperties: false,
          },
        }
      : {}),
    ...(cloudFiles
      ? {
          inventoryScopeSchema: {
            type: "object",
            properties: {
              prefix: {
                type: "string",
                maxLength: 1024,
                title: "Object prefix",
                description:
                  "List files whose paths begin with this literal prefix, including subfolders.",
              },
              format: {
                type: "string",
                enum: ["all", "csv", "tsv", "json", "jsonl", "parquet"],
                title: "File format",
              },
            },
            additionalProperties: false,
          },
        }
      : {}),
    ...(id === "files"
      ? {
          inventoryScopeSchema: {
            type: "object",
            properties: {
              directory: { type: "string", minLength: 1, maxLength: 4000 },
              format: {
                type: "string",
                enum: ["all", "csv", "tsv", "json", "jsonl", "parquet"],
              },
            },
            required: ["directory"],
            additionalProperties: false,
          },
          metadataOptionsSchema: jsonSchemaOptions,
        }
      : {}),
    ...(remoteSchema ? { metadataOptionsSchema: jsonSchemaOptions } : {}),
    actions: [
      "test",
      ...(id === "sql-server" ? ["databases"] : []),
      ...([
        "files",
        "azure-blob",
        "s3",
        "gcs",
        "sftp",
        "sharepoint",
        "onedrive",
        "github",
        "sql-server",
        "postgresql",
        "mysql",
        "oracle",
        "salesforce",
        "hubspot",
        "jira",
        "stripe",
      ].includes(id)
        ? ["sample"]
        : []),
      ...([
        "files",
        "s3",
        "gcs",
        "azure-blob",
        "sftp",
        "sharepoint",
        "onedrive",
        "sql-server",
        "postgresql",
        "mysql",
        "oracle",
        "salesforce",
        "hubspot",
        "jira",
        "stripe",
        "github",
      ].includes(id)
        ? ["inventory", "metadata"]
        : [
              "files",
              "azure-blob",
              "s3",
              "gcs",
              "sftp",
              "sharepoint",
              "onedrive",
            ].includes(id)
          ? ["metadata"]
          : []),
    ],
  };
  writeFileSync(path, await format(stringify(manifest), { parser: "yaml" }));
}
