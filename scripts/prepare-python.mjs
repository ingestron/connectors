import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
let python = "python3.12";
try {
  execFileSync(python, ["--version"], { stdio: "pipe" });
} catch {
  python = execFileSync(
    "uv",
    ["python", "find", "3.12", "--no-python-downloads"],
    { encoding: "utf8" },
  ).trim();
}
mkdirSync("build", { recursive: true });
if (!existsSync("build/singer-github/bin/python"))
  execFileSync(python, ["-m", "venv", "build/singer-github"]);
for (const lock of ["runtime/build-tools.lock", "runtime/github.lock"])
  execFileSync(
    "build/singer-github/bin/python",
    [
      "-I",
      "-m",
      "pip",
      "install",
      "--require-hashes",
      "--no-build-isolation",
      "--index-url",
      "https://pypi.org/simple",
      "-r",
      lock,
    ],
    { stdio: "inherit", env: { ...process.env, PIP_CONFIG_FILE: "/dev/null" } },
  );
