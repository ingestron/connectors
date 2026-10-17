/** Source-owned starter package, without an official catalogue registration. */
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
  renameSync,
  rmSync,
  lstatSync,
} from "node:fs";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import {
  selectionSchema,
  runtimeContract,
  quality,
} from "./connection-contract.mjs";
const owner = fileURLToPath(new URL("../", import.meta.url));
const read = (path) => readFileSync(join(owner, path), "utf8");
const template = (path, id, module, label) =>
  read("src/scaffold/" + path)
    .replaceAll("__ID__", id)
    .replaceAll("__MODULE__", module)
    .replaceAll("__LABEL__", JSON.stringify(label));
const object = (properties) => ({
  type: "object",
  properties,
  required: Object.keys(properties),
  additionalProperties: false,
});
export function scaffold({ id, label = id, out, repository }) {
  if (typeof id !== "string" || !/^[a-z][a-z0-9-]{1,40}$/.test(id))
    throw Error(
      "Use a connector identifier containing 2–41 lowercase letters, digits or hyphens, starting with a letter",
    );
  if (
    typeof label !== "string" ||
    !label.trim() ||
    label.length > 128 ||
    /[\r\n\u0000]/.test(label)
  )
    throw Error("Use a display name of 1–128 characters on one line");
  repository ??= "https://example.invalid/" + id;
  const url = new URL(repository);
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  )
    throw Error("Use a credential-free HTTPS repository URL");
  const directory = resolve(out ?? join("custom", id));
  if (existsSync(directory)) throw Error("Refusing to overwrite " + directory);
  const module = id.replaceAll("-", "_"),
    version = "0.1.0",
    docs = repository.replace(/\/$/, "") + "/blob/main/README.md";
  const settings = object({ directory: { type: "string", minLength: 1 } }),
    tableSource = object({ path: { type: "string", minLength: 1 } });
  const manifest = {
    apiVersion: "ingestron.connector/v1",
    id,
    version,
    description:
      label + " reviewed JSON Lines starter with declared scalar schemas",
    connector: "singer:" + id + "@23.0.1",
    documentation: docs,
    upstream: {
      ecosystem: "singer",
      variant: "custom",
      package: "pyarrow",
      version: "23.0.1",
      repository: "https://github.com/apache/arrow",
      licence: "Apache-2.0",
      licenceFile: "UPSTREAM-LICENSE.txt",
      licenceStatus: "evidenced",
    },
    runtime: {
      path: "runtime.json",
      sha256: "0".repeat(64),
      contract: runtimeContract,
    },
    quality,
    sourceAccess: {
      apiVersion: "ingestron.source-access/v1",
      entryPoint: "source_access.py",
      actions: ["test", "inventory", "metadata", "sample"],
    },
    source: {
      kind: "custom-" + id,
      capabilities: ["snapshot", "discovery"],
      reference: {
        docs,
        vendorStatus: "not-applicable",
        licence: "Original adapter Apache-2.0; upstream pyarrow Apache-2.0",
        cost: { model: "none" },
        access: {
          model: "none",
          note: "Local files inside the configured directory",
        },
        auth: [],
        network: ["local"],
        maturity: "preview",
        verified: new Date().toISOString().slice(0, 10),
        note: "Generated local starter; qualify the adapted source separately",
      },
    },
    definition: {
      settingsSchema: settings,
      selectionSchema,
      tableSourceSchema: tableSource,
    },
    execution: {
      local: {
        modes: ["local"],
        evidence:
          "Generated starter; run its conformance and installed-package gates before release",
      },
    },
  };
  const files = {
    "connector.yaml": JSON.stringify(manifest, null, 2) + "\n",
    "package.json":
      JSON.stringify(
        {
          name: id + "-connector-starter",
          version,
          private: true,
          type: "module",
          engines: { node: ">=22 <23" },
          scripts: {
            build: "node scripts/build.mjs",
            test: ".venv/bin/python -m unittest discover -s test -p test_*.py",
          },
        },
        null,
        2,
      ) + "\n",
    ".gitignore": ".venv/\n__pycache__/\nbuild/\n.ingestron/\n",
    "scripts/build.mjs": template("build.mjs", id, module, label),
    ["runtime/" + module + "_runtime.py"]: template(
      "jsonl_runtime.py",
      id,
      module,
      label,
    ),
    "runtime/source_access.py": template("source_access.py", id, module, label),
    "test/test_connector.py": template("test_connector.py", id, module, label),
    "test/conformance/harness.py": read("test/conformance/harness.py"),
    "runtime/snapshot_runtime.py": read("runtime/singer_runtime.py"),
    "runtime/singer_runtime.py": read("runtime/singer_runtime.py"),
    "runtime/connector_kit.py": read("runtime/connector_kit.py"),
    "runtime/singer_bridge.py": read("runtime/singer_bridge.py"),
    "runtime/metadata_documents.py": read("runtime/metadata_documents.py"),
    "runtime/temporal_types.py": read("runtime/temporal_types.py"),
    "runtime/singer_inventory.py": read("runtime/singer_inventory.py"),
    "runtime/quality_rules.py": read("runtime/quality_rules.py"),
    "runtime/source_sample.py": read("runtime/source_sample.py"),
    "runtime/requirements.lock.txt": read("runtime/files.lock"),
    "runtime/build-tools.lock.txt": read("runtime/build-tools.lock"),
    "runtime/settings.schema.json": JSON.stringify(settings),
    "runtime/connectors.json": JSON.stringify([
      {
        id: id + "@23.0.1",
        package: "pyarrow",
        version: "23.0.1",
        licence: "Apache-2.0",
        executable: id,
        prepared: true,
        supportedStreams: ["records"],
      },
    ]),
    LICENSE: read("LICENSE"),
    "UPSTREAM-LICENSE.txt": read("runtime/files.license.txt"),
    "UPSTREAM-NOTICE.txt": read("runtime/files.notice.txt"),
    "RUNTIME-NOTICES.txt":
      "Original Ingestron adapter: Apache-2.0, Otrera Limited. Apache Arrow retains its upstream licence and notices. Python dependencies are installed separately with their original licences.\n",
    "examples/records.jsonl":
      '{"id":1,"label":"first"}\n{"id":2,"label":"second"}\n',
    "examples/records.jsonl.schema.json":
      JSON.stringify(
        {
          type: "object",
          properties: { id: { type: "integer" }, label: { type: "string" } },
          required: ["id", "label"],
          additionalProperties: false,
        },
        null,
        2,
      ) + "\n",
    "README.md": `# ${label}\n\nThis standalone preview starter reads JSON Lines files inside one configured directory. Each file has a sibling \`<file>.schema.json\` declaring scalar fields. Metadata reads the schema, and samples require the explicit sample action. The shared runtime owns review, contract projection, quality checks and atomic snapshot publication.\n\n## Prepare and test\n\nUse Node 22, Python 3.12 and POSIX. From this directory:\n\n\`\`\`sh\npython3.12 -m venv .venv\n.venv/bin/python -I -m pip install --require-hashes --no-build-isolation -r runtime/build-tools.lock.txt\n.venv/bin/python -I -m pip install --require-hashes --no-build-isolation -r runtime/requirements.lock.txt\nnode scripts/build.mjs\n.venv/bin/python -m unittest discover -s test -p 'test_*.py'\n\`\`\`\n\nThe suite covers the eight shared conformance cases, metadata without row reads, paged inventory, bounded samples, large integers and directory escape rejection. Adapt the source methods, settings/schema declarations and fixture together. Rebuild before recording a new immutable version. Keep dependency hashes and upstream notices current.\n\n## Install a reviewed package\n\nSet your repository and documentation URLs in \`connector.yaml\`; the generated URL is ${repository}. Commit the package and create an immutable version tag in your own repository. Use an explicit manifest reference in project \`packages\`, for example \`owner/repository/connector.yaml@0.1.0\`. Then use the CLI's project package installation operation. Local acceptance may use an immutable local Git snapshot. No official catalogue alias is registered by this scaffold.\n\nA connection names the package alias and uses \`settings: {directory: /absolute/reviewed/directory}\`. Each table uses \`source: {path: records.jsonl}\` and its ODCS contract. Paths are relative to that directory; traversal and symlink escape are rejected. \`examples/\` contains two synthetic records and their schema.\n\n## Limits and qualification\n\nSnapshot and discovery only. No incremental/CDC promise. JSON scalar string, integer, number and boolean fields only, up to 500 columns; each JSON Lines record is limited to 2 MB. Inventory lists top-level JSON Lines files with keyset pages of up to 200 entries and a 10,000-directory-entry bound. Samples read at most 50 rows plus one lookahead, 100 columns, 500 characters per cell and 500 KB of result data; large integers remain exact strings. Samples and receipts stay separate.\n\nThe starter is local preview evidence. Passing its tests does not qualify an adapted vendor connector, authorise a source account or publish this package. Record installed CLI/core/provider acceptance, denial and recovery cases before sharing the adapter with developers.\n`,
  };
  const assets = {};
  for (const name of [
    "snapshot_runtime.py",
    "connector_kit.py",
    "singer_bridge.py",
    "metadata_documents.py",
    "temporal_types.py",
    "singer_inventory.py",
    "quality_rules.py",
    "source_sample.py",
    "source_access.py",
    "requirements.lock.txt",
    "build-tools.lock.txt",
    "settings.schema.json",
    "connectors.json",
  ])
    assets[name] = "runtime/" + name;
  assets["singer_runtime.py"] = "runtime/" + module + "_runtime.py";
  assets[module + "_runtime.py"] = "runtime/" + module + "_runtime.py";
  assets["LICENSE.txt"] = "LICENSE";
  for (const name of [
    "UPSTREAM-LICENSE.txt",
    "UPSTREAM-NOTICE.txt",
    "RUNTIME-NOTICES.txt",
  ])
    assets[name] = name;
  files["runtime-assets.json"] = JSON.stringify(assets, null, 2) + "\n";
  mkdirSync(dirname(directory), { recursive: true });
  const stage = mkdtempSync(join(dirname(directory), "." + id + "-scaffold-"));
  try {
    for (const [path, content] of Object.entries(files)) {
      const target = join(stage, path);
      mkdirSync(dirname(target), { recursive: true });
      writeFileSync(target, content, { flag: "wx" });
    }
    execFileSync(process.execPath, [join(stage, "scripts/build.mjs")], {
      stdio: "pipe",
    });
    // Reserve a new destination before publication. Existing directories, even
    // empty ones, are refused; a later collision cannot leave partial files.
    mkdirSync(directory);
    const reserved = lstatSync(directory);
    if (!reserved.isDirectory()) throw Error("Invalid destination");
    renameSync(stage, directory);
  } catch (error) {
    rmSync(stage, { recursive: true, force: true });
    throw error;
  }
  return { id, directory, files: Object.keys(files) };
}
