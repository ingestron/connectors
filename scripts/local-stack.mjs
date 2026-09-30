// Local integration stack (PB-064): the CLI and core from sibling checkouts,
// installed together without npm publication, so connector gates can run
// against unreleased work. Usage:
//   pnpm local-stack [--core ../core] [--cli ../cli]
//   INGESTRON_TEST_CLI=$(pnpm -s local-stack --print) pnpm acceptance:files:tables
// The CLI is repacked to declare exactly the local core version, so installed
// gates keep their "exact declared core" check.
import { execFileSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const args = process.argv.slice(2);
const option = (name, fallback) => {
  const i = args.indexOf(name);
  return resolve(i >= 0 ? args[i + 1] : fallback);
};
const quiet = args.includes("--print");
const log = (m) => quiet || console.error(m);
const core = option("--core", "../core");
const cli = option("--cli", "../cli");
const stack = resolve("build/local-stack");
const run = (cmd, cmdArgs, cwd) =>
  execFileSync(cmd, cmdArgs, {
    cwd,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });

rmSync(stack, { recursive: true, force: true });
mkdirSync(stack, { recursive: true });
const pack = (dir) => {
  log(`Building ${dir}`);
  run("pnpm", ["-s", "build"], dir);
  const out = JSON.parse(
    run(
      "npm",
      ["pack", "--json", "--ignore-scripts", "--pack-destination", stack],
      dir,
    ),
  )[0];
  return {
    file: join(stack, out.filename),
    version: out.version,
    name: out.name,
  };
};
const corePack = pack(core);
const cliPack = pack(cli);

// Repack the CLI so it declares the local core version exactly.
const work = mkdtempSync(join(tmpdir(), "ingestron-cli-"));
run("tar", ["-xzf", cliPack.file, "-C", work]);
const manifestPath = join(work, "package", "package.json");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
manifest.dependencies["@ingestron/core"] = corePack.version;
writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + "\n");
const cliFile = join(stack, `ingestron-local-${cliPack.version}.tgz`);
run("tar", ["-czf", cliFile, "-C", work, "package"]);
rmSync(work, { recursive: true, force: true });

writeFileSync(
  join(stack, "package.json"),
  JSON.stringify(
    {
      private: true,
      dependencies: { ingestron: `file:${cliFile}` },
      overrides: { "@ingestron/core": `file:${corePack.file}` },
    },
    null,
    2,
  ),
);
log("Installing the local stack");
run("npm", ["install", "--no-audit", "--no-fund", "--prefer-online"], stack);
const entry = join(stack, "node_modules/ingestron/build/cli/cli/index.js");
const version = run("node", [entry, "--version"], stack).trim();
log(`Local CLI ${version} with core ${corePack.version}`);
if (quiet) console.log(entry);
else console.error(`INGESTRON_TEST_CLI=${entry}`);
