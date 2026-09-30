// Scaffold a table connector on the connector kit (PB-064 phase 3).
// Usage: pnpm connector:new <id> [--label "Display name"] [--out <directory>]
// The scaffold is a working example (one JSON Lines file per table) that passes
// the conformance suite; replace scan() and the fixture with the real source.
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const args = process.argv.slice(2);
const id = args.find((a) => !a.startsWith("--"));
const option = (name) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : undefined;
};
if (!id || !/^[a-z][a-z0-9-]{1,40}$/.test(id)) {
  console.error(
    "Usage: pnpm connector:new <id> [--label <name>] [--out <dir>]",
  );
  process.exit(2);
}
const label = option("--label") ?? id;
const out = option("--out") ?? ".";
const module = id.replaceAll("-", "_");
const className = module
  .split("_")
  .map((p) => p[0].toUpperCase() + p.slice(1))
  .join("");
const files = {
  [`runtime/${module}_runtime.py`]: `"""${label} tables through the connector kit.

Scaffolded example: each table reads one JSON Lines file. Replace settings(),
table() and scan() with the real source; keep errors free of source values.
"""
import json
from pathlib import Path

import connector_kit as kit

TYPES = {'integer': 'integer', 'string': 'string', 'number': 'number', 'boolean': 'boolean'}


class ${className}(kit.TableConnector):
    name = ${JSON.stringify(label)}
    table_keys = frozenset({'path'})
    errors = {
        'SOURCE_UNAVAILABLE': ${JSON.stringify(`${label} source is not available. Check the path and permissions.`)},
    }

    def table(self, source, columns):
        return {'path': source['path'],
                'columns': {c['name']: TYPES[c.get('logicalType', 'string')] for c in columns}}

    def scan(self, settings, table, emit=None):
        path = Path(table['path'])
        if not path.is_file():
            raise kit.SourceError('SOURCE_UNAVAILABLE')
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        names = sorted({key for row in rows for key in row}) or sorted(table['columns'])
        schema = {'type': 'object',
                  'properties': {n: {'type': ['null', table['columns'].get(n, 'string')]} for n in names},
                  'additionalProperties': False}
        if emit:
            for row in rows:
                emit({n: row.get(n) for n in names})
        return schema


connector = ${className}()
workflow = kit.install(connector)
runtime_identity = workflow.runtime_identity
if __name__ == '__main__': workflow.main()
`,
  [`test/runtime/test_conformance_${module}.py`]: `"""${label} passes the shared conformance suite."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'conformance'))
from harness import Conformance, singer_runtime

_before = (singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review)
import ${module}_runtime as runtime
singer_runtime.source_config, singer_runtime.tap_output, singer_runtime.review = _before


class ${className}Conformance(Conformance, unittest.TestCase):
    def make_connector(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        return runtime.${className}()

    def settings(self):
        return {}

    def tables(self):
        return {name: {'source': {'path': str(self.root / f'{name}.jsonl')},
                       'columns': [{'name': 'id', 'logicalType': 'integer'},
                                   {'name': 'label', 'logicalType': 'string'}]}
                for name in ('first', 'second')}

    def rows(self, stream):
        return [{'id': 1, 'label': 'a'}, {'id': 2, 'label': 'b'}]

    def load(self, stream, rows):
        (self.root / f'{stream}.jsonl').write_text(''.join(json.dumps(r) + '\\n' for r in rows))

    def change_schema(self, stream):
        (self.root / f'{stream}.jsonl').write_text(json.dumps({'id': 1, 'extra': True}) + '\\n')

    def break_source(self, stream):
        (self.root / f'{stream}.jsonl').unlink()

    def secret_values(self):
        return []


if __name__ == '__main__':
    unittest.main()
`,
  [`docs/${id}.md`]: `# ${label}

One paragraph: what this connector reads, into what, and what it never does.

| Package  | \`${id}@0.1.0\` |
| -------- | --- |
| Kind     | \`${id}\` |
| Maturity | preview: conformance suite against fakes |
| Licence  | Adapter Apache-2.0; upstream … |
| Cost     | … |

## Install

\`\`\`sh
ingestron connector install ${id}@0.1.0
\`\`\`

## Connection

Access, permissions and credentials (always \`$secret\` references), with a
\`connections\` and \`flows\` example.

## Tables

| \`source\` key | Meaning |
| --- | --- |
| \`path\` | … |

## Types

## Behaviour and limits

## Evidence

Start as preview; move to verified only with recorded tests against the real
service.

## References
`,
};
for (const [path, content] of Object.entries(files)) {
  const target = join(out, path);
  if (existsSync(target)) {
    console.error(`Refusing to overwrite ${target}`);
    process.exit(1);
  }
  mkdirSync(join(target, ".."), { recursive: true });
  writeFileSync(target, content);
  console.log(`Created ${target}`);
}
console.log(`
Next:
  1. Replace scan() in runtime/${module}_runtime.py and the fixture in
     test/runtime/test_conformance_${module}.py with the real source.
  2. Add a build entry (see scripts/build-database.mjs), pinned requirements
     (runtime/${module}.in and a hash-locked .lock) and the upstream licence.
  3. Add a reference record to src/sources.mjs with maturity: preview.
  4. Run pnpm runtime:test; the conformance suite must pass.`);
