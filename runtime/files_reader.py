"""Explicit local file access and flat format readers; no network or path discovery."""
from pathlib import Path
from decimal import Decimal
import csv
import json
import math
import re
import stat
import os
import pyarrow as pa
import pyarrow.parquet as pq

MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 1_000_000
NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
KINDS = {'string','integer','decimal','number','boolean'}

def require(value, message):
    if not value: raise ValueError(message)

def local_path(settings):
    path = Path(settings['path'])
    require(path.is_absolute(), 'Use an absolute local file path')
    require('..' not in path.parts and not any(p.is_symlink() for p in [path, *path.parents]), 'Symlink/traversal inputs are not supported')
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_size <= MAX_BYTES, 'Use one regular file up to 64 MiB')
    return path

def unique_object(pairs):
    result = {}
    for key,value in pairs:
        require(key not in result, 'Duplicate JSON property')
        result[key] = value
    return result

def parse_json(text):
    return json.loads(text, parse_float=Decimal, object_pairs_hook=unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON number')))

def arrow_kind(t):
    if pa.types.is_integer(t): return 'integer'
    if pa.types.is_decimal(t): return 'decimal'
    if pa.types.is_floating(t): return 'number'
    if pa.types.is_boolean(t): return 'boolean'
    if pa.types.is_string(t) or pa.types.is_large_string(t): return 'string'
    if pa.types.is_null(t): return 'string'
    raise ValueError('Unsupported Parquet type; nested, binary and temporal fields need an explicit future mapping')

def raw_rows(handle, fmt):
    if fmt in ('csv','tsv'):
        import io
        with io.TextIOWrapper(handle, encoding='utf-8-sig', newline='') as text:
            reader = csv.reader(text, delimiter='\t' if fmt == 'tsv' else ',', strict=True)
            names = next(reader, None)
            require(names and len(names) == len(set(names)), 'Missing or duplicate delimited header')
            yield names, {name:'string' for name in names}
            for values in reader:
                require(len(values) == len(names), 'Delimited row width differs from header')
                yield dict(zip(names, [None if v == '' else v for v in values]))
    elif fmt == 'parquet':
        file = pq.ParquetFile(handle)
        names = file.schema_arrow.names
        require(len(names) == len(set(names)), 'Duplicate Parquet fields')
        yield names, {f.name:arrow_kind(f.type) for f in file.schema_arrow}
        for batch in file.iter_batches(batch_size=1024):
            yield from batch.to_pylist()
    elif fmt in ('json','jsonl'):
        yield [], {}
        if fmt == 'json':
            data = parse_json(handle.read().decode('utf-8-sig'))
            require(isinstance(data,list), 'JSON input must be an array of flat objects')
            yield from data
        else:
            for line in handle:
                require(len(line) <= 2_000_000, 'JSONL record exceeds 2 MB')
                require(line.strip(), 'Blank JSONL record')
                yield parse_json(line.decode('utf-8'))
    else: raise ValueError('Unsupported file format')

def kind(value):
    if value is None: return None
    if isinstance(value,bool): return 'boolean'
    if isinstance(value,int): return 'integer'
    if isinstance(value,Decimal): return 'decimal'
    if isinstance(value,float):
        require(math.isfinite(value), 'Nonfinite number')
        return 'number'
    if isinstance(value,str): return 'string'
    raise ValueError('Only flat scalar fields are supported; nested values are not flattened')

def convert(value, target):
    if value is None: return None
    original = kind(value)
    if target == original: return value
    if target == 'integer' and isinstance(value,str) and re.fullmatch(r'-?(0|[1-9][0-9]*)',value): return int(value)
    if target == 'decimal' and not isinstance(value,bool) and isinstance(value,(str,int,Decimal)):
        d = Decimal(value); require(d.is_finite(), 'Nonfinite decimal'); return d
    if target == 'number' and not isinstance(value,bool) and isinstance(value,(str,int,float,Decimal)):
        n=float(value); require(math.isfinite(n), 'Nonfinite number'); return n
    if target == 'boolean' and isinstance(value,str) and value in ('true','false'): return value == 'true'
    raise ValueError('Input value does not match declared type')

def scan(settings, emit=None):
    """Use a single non-symlink descriptor and reject inputs modified during a read."""
    path = local_path(settings)
    overrides = settings.get('types', {})
    require(all(NAME.fullmatch(k) and v in KINDS for k,v in overrides.items()), 'Invalid column type mapping')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as handle:
        before = os.fstat(handle.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_BYTES, 'Invalid input file')
        rows = raw_rows(handle, settings['format'])
        names, inferred = next(rows)
        expected = set(names) if names else None
        count = 0
        for row in rows:
            count += 1
            require(count <= MAX_ROWS, 'File exceeds one million rows')
            require(isinstance(row,dict) and row, 'Each row must be a nonempty flat object')
            require(len(row) <= 500 and all(NAME.fullmatch(k) for k in row), 'Use at most 500 simple column names')
            if expected is None: expected=set(row)
            require(set(row) == expected, 'Rows have inconsistent columns')
            values = {}
            for name,value in row.items():
                target = overrides.get(name)
                value = convert(value,target) if target else value
                observed = target or kind(value)
                prior = inferred.get(name)
                if name in overrides: inferred[name]=target
                elif observed is not None:
                    require(prior is None or prior == observed, 'Mixed column types; declare a supported type explicitly')
                    inferred[name]=observed
                values[name]=value
            if emit: emit(values)
        expected = expected if expected is not None else set(overrides)
        require(expected and len(expected) <= 500 and all(NAME.fullmatch(n) for n in expected), 'Empty input needs headers, Parquet schema or explicit types')
        require(set(overrides) <= expected, 'Declared type refers to an absent field')
        after = path.stat()
        require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns) == (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns), 'Input changed during read')
    mapping = {'string':'string','integer':'integer','boolean':'boolean','number':'number','decimal':'number'}
    return {'type':'object','properties':{name:{'type':['null',mapping[overrides.get(name) or inferred.get(name) or 'string']]} for name in sorted(expected)},'additionalProperties':False}, count
