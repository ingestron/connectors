"""Custom connector starter: confined JSON Lines with declared scalar schema.

Adapt the source methods; keep safe errors and shared reviewed publication.
"""
import json
import math
from pathlib import Path
import jsonschema
import connector_kit as kit

MAX_LINE = 2_000_000
MAX_SCHEMA = 1_000_000
KINDS = {'string', 'integer', 'number', 'boolean'}


def fail(code):
    raise kit.SourceError(code)


def folder(settings):
    if not isinstance(settings, dict) or set(settings) != {'directory'}:
        fail('SOURCE_SETTINGS')
    value = settings['directory']
    if not isinstance(value, str) or not Path(value).is_absolute():
        fail('SOURCE_SETTINGS')
    try:
        root = Path(value).resolve(strict=True)
        if not root.is_dir(): fail('SOURCE_UNAVAILABLE')
        return root
    except OSError:
        fail('SOURCE_UNAVAILABLE')


def path(settings, source):
    value = source.get('path')
    if set(source) != {'path'} or not isinstance(value, str) or not value.endswith('.jsonl'):
        fail('SOURCE_PATH')
    relative = Path(value)
    if relative.is_absolute() or any(part in ('.', '..') for part in relative.parts) or '\\' in value:
        fail('SOURCE_PATH')
    root = folder(settings)
    try:
        result = (root / relative).resolve(strict=True)
        if not result.is_relative_to(root) or not result.is_file(): fail('SOURCE_PATH')
        return result
    except OSError:
        fail('SOURCE_UNAVAILABLE')


def schema(settings, source):
    data = path(settings, source)
    file = Path(str(data) + '.schema.json')
    try:
        if not file.resolve(strict=True).is_relative_to(folder(settings)) or file.stat().st_size > MAX_SCHEMA:
            fail('SOURCE_SCHEMA')
        value = json.loads(file.read_text())
    except (OSError, ValueError):
        fail('SOURCE_SCHEMA')
    if not isinstance(value, dict) or set(value) - {'type', 'properties', 'required', 'additionalProperties'}:
        fail('SOURCE_SCHEMA')
    props = value.get('properties')
    if value.get('type') != 'object' or value.get('additionalProperties') is not False or not isinstance(props, dict) or not 1 <= len(props) <= 500:
        fail('SOURCE_SCHEMA')
    for name, spec in props.items():
        if not isinstance(name, str) or not 1 <= len(name) <= 128 or not isinstance(spec, dict) or set(spec) != {'type'}:
            fail('SOURCE_SCHEMA')
        types = spec['type'] if isinstance(spec['type'], list) else [spec['type']]
        if len(types) != len(set(types)) or not 1 <= len(types) <= 2 or len(set(types) - {'null'}) != 1 or not set(types) <= KINDS | {'null'}:
            fail('SOURCE_SCHEMA')
    required = value.get('required', [])
    if not isinstance(required, list) or not all(isinstance(n, str) for n in required) or len(required) != len(set(required)) or not set(required) <= set(props):
        fail('SOURCE_SCHEMA')
    return value


def records(settings, source, declaration):
    validator = jsonschema.Draft202012Validator(declaration)
    try:
        with path(settings, source).open('rb') as handle:
            while True:
                line = handle.readline(MAX_LINE + 1)
                if not line: break
                if len(line) > MAX_LINE: fail('SOURCE_RECORD')
                if not line.strip(): continue
                row = json.loads(line, parse_constant=lambda _: fail('SOURCE_RECORD'))
                if not isinstance(row, dict) or any(isinstance(v, float) and not math.isfinite(v) for v in row.values()): fail('SOURCE_RECORD')
                validator.validate(row)
                yield row
    except (OSError, ValueError, jsonschema.ValidationError):
        fail('SOURCE_RECORD')


class Starter(kit.TableConnector):
    name = __LABEL__
    table_keys = frozenset({'path'})
    errors = {code: code.replace('_', ' ').capitalize() + '. Review the connector settings and declared schema.'
              for code in ('SOURCE_SETTINGS', 'SOURCE_UNAVAILABLE', 'SOURCE_PATH', 'SOURCE_SCHEMA', 'SOURCE_RECORD')}

    def settings(self, settings):
        folder(settings)
        return settings

    def table(self, source, columns):
        return {'path': source['path']}

    def scan(self, settings, table, emit=None):
        declaration = schema(settings, table)
        if emit:
            for row in records(settings, table, declaration): emit(row)
        return declaration

    def catalogue(self, settings, source):
        declaration = schema(settings, source)
        return [{'name': name, 'type': next(t for t in (spec['type'] if isinstance(spec['type'], list) else [spec['type']]) if t != 'null'),
                 'nullable': 'null' in spec['type'] or name not in declaration.get('required', [])}
                for name, spec in declaration['properties'].items()]


connector = Starter()
workflow = kit.install(connector)
runtime_identity = workflow.runtime_identity
if __name__ == '__main__': workflow.main()
