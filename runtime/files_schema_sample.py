"""Explicit, byte-bounded JSON schema suggestions; no business values in results."""
import codecs
from contextlib import contextmanager
from decimal import Decimal
import json
import math
import os
import stat
from files_reader import local_path, unique_object, convert
from source_access import AccessError, object_entry

MAX_BYTES = 1048576
MAX_FIELDS = 100


def require(value, code='SAMPLE_SHAPE'):
    if not value:
        raise AccessError(code)


def records(handle, fmt):
    """Parse a prefix only. Never read an unbounded JSONL line or JSON array."""
    decoder = json.JSONDecoder(parse_float=Decimal, object_pairs_hook=unique_object,
        parse_constant=lambda _: (_ for _ in ()).throw(AccessError('SAMPLE_VALUE')))
    utf8 = codecs.getincrementaldecoder('utf-8-sig')()
    buffer = ''
    total = 0
    eof = False
    def read():
        nonlocal buffer, total, eof
        part = handle.read(min(4096, MAX_BYTES - total + 1))
        total += len(part)
        require(total <= MAX_BYTES, 'SAMPLE_TOO_LARGE')
        eof = not part
        buffer += utf8.decode(part, final=eof)
    def whitespace():
        nonlocal buffer
        while True:
            buffer = buffer.lstrip(' \t\r\n')
            if buffer or eof:
                return
            read()
    if fmt == 'jsonl':
        while True:
            while '\n' not in buffer and not eof:
                read()
            if not buffer and eof:
                return
            line, separator, buffer = buffer.partition('\n')
            require(line.strip(), 'SAMPLE_SHAPE')
            yield decoder.decode(line)
            if not separator:
                return
    else:
        whitespace()
        require(buffer.startswith('['))
        buffer = buffer[1:]
        first = True
        while True:
            whitespace()
            if buffer.startswith(']'):
                buffer = buffer[1:]
                whitespace()
                require(eof and not buffer)
                return
            if not first:
                require(buffer.startswith(','))
                buffer = buffer[1:]
                whitespace()
                require(not buffer.startswith(']'))
            while True:
                try:
                    row, end = decoder.raw_decode(buffer)
                    break
                except json.JSONDecodeError:
                    require(not eof)
                    read()
            buffer = buffer[end:]
            yield row
            first = False


def column_kind(value):
    if value is None:
        return None
    if type(value) is bool:
        return 'boolean'
    if type(value) is int:
        return 'integer' if -(2**63) <= value < 2**63 else 'integer-outside-int64'
    if isinstance(value, Decimal):
        if not value.is_finite():
            return 'nonfinite-number'
        digits = value.as_tuple().digits
        exponent = value.as_tuple().exponent
        scale = max(0, -exponent)
        integer_digits = max(0, len(digits) + exponent)
        return 'decimal' if integer_digits + scale <= 38 else 'decimal-outside-precision38'
    if isinstance(value, str):
        return 'string'
    if type(value) is float:
        return 'number' if math.isfinite(value) else 'nonfinite-number'
    return 'nested-object' if isinstance(value, dict) else 'nested-array' if isinstance(value, list) else 'unsupported-value'


@contextmanager
def stable_file(source):
    """One unbuffered descriptor, with exact path/identity fences around access."""
    path = local_path(source)
    expected = path.stat(follow_symlinks=False)
    stamp = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb', buffering=0) as handle:
        before = os.fstat(handle.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= 64 * 1024 * 1024
                and stamp(expected) == stamp(before) == stamp(path.stat(follow_symlinks=False)), 'ACCESS_CHANGED')
        yield path, handle
        after = os.fstat(handle.fileno())
        current = path.stat(follow_symlinks=False)
        require(stamp(before) == stamp(after) == stamp(current)
                and not any(parent.is_symlink() for parent in path.parents), 'ACCESS_CHANGED')


def prefix(source, limit, max_fields=MAX_FIELDS):
    require(type(limit) is int and 1 <= limit <= 50, 'SAMPLE_LIMIT')
    require(source.get('format') in ('json', 'jsonl'), 'SAMPLE_FORMAT')
    with stable_file(source) as opened:
        path, handle = opened
        result, names, truncated = [], None, False
        for row in records(handle, source['format']):
            require(isinstance(row, dict) and row and len(row) <= max_fields)
            require(all(isinstance(name, str) and 1 <= len(name) <= 128 for name in row))
            if names is None:
                names = set(row)
            require(set(row) == names)
            if len(result) == limit:
                truncated = True
                break
            result.append(row)
        require(result, 'SAMPLE_EMPTY')
    return path, result, truncated


def data_sample(request):
    """Return selected scalar business values only after the source fence passes."""
    from source_sample import cell, MAX_COLUMNS
    requested = request.get('columns')
    if requested is not None:
        require(isinstance(requested, list) and 1 <= len(requested) <= MAX_COLUMNS
                and all(isinstance(name, str) for name in requested)
                and len(set(requested)) == len(requested), 'SAMPLE_COLUMNS')
    _, rows, truncated = prefix(request['source'], request.get('limit', 20), max_fields=500)
    names = list(rows[0])
    chosen = requested if requested is not None else names[:MAX_COLUMNS]
    require(set(chosen) <= set(names), 'SAMPLE_COLUMNS')
    result = {'columns': chosen, 'rows': [[cell(row[name]) for name in chosen] for row in rows],
              'truncated': truncated}
    while len(json.dumps(result).encode()) > 500_000 and result['rows']:
        result['rows'].pop()
        result['truncated'] = True
    return result


def schema_sample(source, options):
    limit = options.get('limit', 20)
    path, rows, truncated = prefix(source, limit)
    names = set(rows[0])
    observed, scales, integer_digits = {}, {}, {}
    overrides = source.get('types', {})
    require(set(overrides) <= names)
    for row in rows:
        for name, value in row.items():
            if name in overrides:
                value = convert(value, overrides[name])
            kind = column_kind(value)
            if kind is not None:
                observed.setdefault(name, set()).add(kind)
            if isinstance(value, Decimal) and kind == 'decimal':
                scales[name] = max(scales.get(name, 0), max(0, -value.as_tuple().exponent))
                integer_digits[name] = max(integer_digits.get(name, 0), max(0, len(value.as_tuple().digits) + value.as_tuple().exponent))
    count = len(rows)
    columns = []
    for name in sorted(names):
        kinds = observed.get(name, set())
        chosen = next(iter(kinds)) if len(kinds) == 1 else 'all-null' if not kinds else 'mixed-types'
        # An explicit scalar override also defines an all-null field; sampling cannot prove requiredness.
        if not kinds and name in overrides:
            chosen = overrides[name]
        supported = chosen in ('string', 'integer', 'decimal', 'number', 'boolean')
        if chosen == 'decimal' and scales.get(name, 0) + integer_digits.get(name, 0) > 38:
            chosen, supported = 'decimal-outside-precision38', False
        column = {'name': name, 'type': chosen if supported else 'string', 'nullable': True}
        if not supported:
            column.update(supported=False, sourceType=chosen)
        elif chosen == 'decimal':
            column.update(precision=38, scale=scales.get(name, 9))
        columns.append(column)
    result = object_entry(source, path.name, 'file', columns)
    result['sampling'] = {'method': 'bounded-records', 'rowCount': count, 'limit': limit,
                          'byteLimit': MAX_BYTES, 'truncated': truncated}
    return result
