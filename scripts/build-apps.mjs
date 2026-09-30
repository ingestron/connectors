// Stripe, SharePoint and OneDrive connectors on the connector kit (PB-064 phase 4).
// They use only the Python standard library for HTTPS and share the file
// readers' pinned Apache Arrow runtime.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { createHash } from "node:crypto";
import { stringify } from "yaml";
import { format } from "prettier";
import {
  stripeSettings,
  stripeTableSource,
  sharepointSettings,
  onedriveSettings,
  graphTableSource,
  graphFileSource,
  s3Settings,
  gcsSettings,
  sftpSettings,
  fileTableSource,
  salesforceSettings,
  hubspotSettings,
  jiraSettings,
  objectTableSource,
  jiraTableSource,
} from "../src/app-settings.mjs";
import {
  selectionSchema,
  runtimeContract,
  quality,
} from "../src/connection-contract.mjs";
import { sources } from "../src/sources.mjs";

const sha = (v) => createHash("sha256").update(v).digest("hex");
const read = (p) => readFileSync(p, "utf8");
const graphFiles = {
  "graph_runtime.py": read("runtime/graph_runtime.py"),
  "graph_reader.py": read("runtime/graph_reader.py"),
  "files_reader.py": read("runtime/files_reader.py"),
};
const objectFiles = {
  "object_store_runtime.py": read("runtime/object_store_runtime.py"),
  "object_store_reader.py": read("runtime/object_store_reader.py"),
  "files_reader.py": read("runtime/files_reader.py"),
};
const rest = (id) => ({
  [`${id}_reader.py`]: read(`runtime/${id}_reader.py`),
  "rest_client.py": read("runtime/rest_client.py"),
});
const connectors = [
  {
    id: "stripe",
    description: "Reviewed local snapshots of Stripe objects",
    runtime: "runtime/stripe_runtime.py",
    files: { "stripe_reader.py": read("runtime/stripe_reader.py") },
    settings: stripeSettings,
    tableSource: stripeTableSource,
    evidence:
      "Read-only Stripe list API over HTTPS; conformance suite against a mock of the documented list API",
  },
  {
    id: "sharepoint",
    description:
      "Reviewed local snapshots of SharePoint files through Microsoft Graph",
    runtime: "runtime/sharepoint_runtime.py",
    files: graphFiles,
    settings: sharepointSettings,
    tableSource: graphTableSource,
    evidence:
      "Read-only Microsoft Graph file reads with app-only credentials; conformance suite against a Graph mock",
  },
  {
    id: "onedrive",
    description:
      "Reviewed local snapshots of OneDrive files through Microsoft Graph",
    runtime: "runtime/onedrive_runtime.py",
    files: graphFiles,
    settings: onedriveSettings,
    tableSource: graphFileSource,
    evidence:
      "Read-only Microsoft Graph file reads with app-only credentials; unit tests against a Graph mock",
  },
  {
    id: "s3",
    version: "1.0.0",
    description: "Reviewed local snapshots of Amazon S3 objects",
    runtime: "runtime/s3_runtime.py",
    files: objectFiles,
    settings: s3Settings,
    tableSource: fileTableSource,
    evidence:
      "SigV4-signed S3 API reads; conformance suite against a mock and against an S3-compatible server in a local container",
  },
  {
    id: "gcs",
    description: "Reviewed local snapshots of Google Cloud Storage objects",
    runtime: "runtime/gcs_runtime.py",
    files: objectFiles,
    settings: gcsSettings,
    tableSource: fileTableSource,
    evidence:
      "HMAC-signed Cloud Storage XML API reads; conformance suite against a mock",
  },
  {
    id: "sftp",
    version: "1.0.0",
    description: "Reviewed local snapshots of files on SFTP servers",
    runtime: "runtime/sftp_runtime.py",
    files: {
      "sftp_reader.py": read("runtime/sftp_reader.py"),
      "files_reader.py": read("runtime/files_reader.py"),
    },
    settings: sftpSettings,
    tableSource: fileTableSource,
    evidence:
      "System OpenSSH sftp client with a pinned host key; conformance suite against a local transport and an SFTP server container",
  },
  {
    id: "salesforce",
    description: "Reviewed local snapshots of Salesforce objects",
    runtime: "runtime/salesforce_runtime.py",
    files: rest("salesforce"),
    settings: salesforceSettings,
    tableSource: objectTableSource,
    evidence:
      "Salesforce REST API (describe and SOQL query); conformance suite against a mock of the documented API",
  },
  {
    id: "hubspot",
    description: "Reviewed local snapshots of HubSpot CRM objects",
    runtime: "runtime/hubspot_runtime.py",
    files: rest("hubspot"),
    settings: hubspotSettings,
    tableSource: objectTableSource,
    evidence:
      "HubSpot CRM v3 API (properties and objects); conformance suite against a mock of the documented API",
  },
  {
    id: "jira",
    description: "Reviewed local snapshots of Jira Cloud issues and projects",
    runtime: "runtime/jira_runtime.py",
    files: rest("jira"),
    settings: jiraSettings,
    tableSource: jiraTableSource,
    evidence:
      "Jira Cloud REST API v3 (fields, enhanced JQL search); conformance suite against a mock of the documented API",
  },
];
for (const c of connectors) {
  const dir = "connectors/" + c.id;
  const runtimeId = `${c.id}@23.0.1`;
  const files = {
    "singer_runtime.py": read(c.runtime),
    ...c.files,
    "snapshot_runtime.py": read("runtime/singer_runtime.py"),
    "singer_bridge.py": read("runtime/singer_bridge.py"),
    "connector_kit.py": read("runtime/connector_kit.py"),
    "quality_rules.py": read("runtime/quality_rules.py"),
    "singer_inventory.py": read("runtime/singer_inventory.py"),
    "connectors.json": JSON.stringify([
      {
        id: runtimeId,
        package: "pyarrow",
        version: "23.0.1",
        licence: "Apache-2.0",
        executable: c.id,
        prepared: true,
        supportedStreams: [],
      },
    ]),
    "settings.schema.json": JSON.stringify(c.settings),
    "requirements.lock.txt": read("runtime/files.lock"),
    "build-tools.lock.txt": read("runtime/build-tools.lock"),
    "UPSTREAM-LICENSE.txt": read("runtime/files.license.txt"),
    "LICENSE.txt": read("LICENSE"),
    "UPSTREAM-NOTICE.txt": read("runtime/files.notice.txt"),
    "RUNTIME-NOTICES.txt":
      "Original Ingestron adapter: Apache-2.0, Otrera Limited. HTTPS uses the Python standard library. Apache Arrow retains its bundled upstream notices. Python dependencies are installed separately with their original licences.\n",
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
    version: c.version ?? "0.1.0",
    description: c.description,
    connector: `singer:${runtimeId}`,
    documentation: `https://github.com/ingestron/connectors/blob/main/docs/${c.id}.md`,
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
    quality,
    source: sources[c.id],
    definition: {
      settingsSchema: c.settings,
      selectionSchema,
      tableSourceSchema: c.tableSource,
    },
    execution: { local: { modes: ["local"], evidence: c.evidence } },
  };
  writeFileSync(
    dir + "/connector.yaml",
    await format(stringify(manifest), { parser: "yaml" }),
  );
}
