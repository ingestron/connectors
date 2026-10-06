/** Generate a complete standalone connector starter. */
import { scaffold } from "../src/connector-scaffold.mjs";
try {
  const args = process.argv.slice(2),
    options = {};
  const id = args.shift();
  while (args.length) {
    const name = args.shift();
    if (
      !["--label", "--out", "--repository"].includes(name) ||
      !args.length ||
      args[0].startsWith("--")
    )
      throw Error(
        "Use <id> [--label <name>] [--out <new-directory>] [--repository <https-url>]",
      );
    if (Object.hasOwn(options, name)) throw Error("Repeated option " + name);
    options[name] = args.shift();
  }
  const result = scaffold({
    id,
    label: options["--label"],
    out: options["--out"],
    repository: options["--repository"],
  });
  console.log(
    "Created standalone connector " + result.id + " at " + result.directory,
  );
  console.log(
    "Read README.md to prepare its hash-locked Python runtime, run conformance and install an immutable Git reference.",
  );
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
