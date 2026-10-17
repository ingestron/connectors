"""Bounded local delimited/Parquet metadata and explicit business previews."""
import csv
import io
import json
from files_schema_sample import stable_file, require, prefix, MAX_BYTES
from source_access import AccessError, object_entry
from source_sample import cell, MAX_CELL
from decimal import Decimal

MAX_HEADER = 65536
MAX_UNCOMPRESSED = 8 * 1024 * 1024


class BudgetReader(io.RawIOBase):
    """Count actual reads including random-access Parquet pages; own no descriptor."""
    def __init__(self, handle, maximum=MAX_BYTES):
        self.handle, self.maximum, self.total, self.exceeded = handle, maximum, 0, False
    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.handle.tell()
    def seek(self, offset, whence=0): return self.handle.seek(offset, whence)
    def read(self, size=-1):
        remaining = self.maximum - self.total
        size = remaining + 1 if size is None or size < 0 else min(size, remaining + 1)
        result = self.handle.read(size)
        self.total += len(result)
        if self.total > self.maximum:
            self.exceeded = True
            raise AccessError('SAMPLE_TOO_LARGE')
        return result
    def readinto(self, target):
        result = self.read(len(target)); target[:len(result)] = result; return len(result)


def names_valid(names):
    require(names and len(names) <= 500 and len(set(names)) == len(names)
            and all(isinstance(name, str) and 1 <= len(name) <= 128 for name in names), 'SAMPLE_SHAPE')


def selection(names, requested):
    chosen = requested if requested is not None else names[:100]
    require(set(chosen) <= set(names), 'SAMPLE_COLUMNS')
    return chosen


def header_lines(handle):
    """Consume only the delimited header, including quoted physical newlines."""
    total = 0
    while True:
        line = bytearray()
        while True:
            part = handle.read(1)
            if not part:
                break
            total += 1
            require(total <= MAX_HEADER, 'ACCESS_TOO_LARGE')
            line.extend(part)
            if part == b'\n':
                break
        if not line:
            return
        yield bytes(line).decode('utf-8-sig' if total == len(line) else 'utf-8')


def parquet_metadata(handle):
    """Read only magic and footer bytes, without decoding or fetching data pages."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    handle.seek(0, 2); size = handle.tell()
    require(size >= 12, 'SAMPLE_FORMAT')
    handle.seek(0); require(handle.read(4) == b'PAR1', 'SAMPLE_FORMAT')
    handle.seek(-8, 2); trailer = handle.read(8)
    require(len(trailer) == 8 and trailer[4:] == b'PAR1', 'SAMPLE_FORMAT')
    length = int.from_bytes(trailer[:4], 'little')
    require(0 < length <= size - 12 and length + 12 <= MAX_BYTES, 'SAMPLE_TOO_LARGE')
    handle.seek(size - length - 8); footer = handle.read(length)
    require(len(footer) == length, 'ACCESS_CHANGED')
    view = pa.BufferReader(b'PAR1' + footer + trailer)
    metadata = pq.ParquetFile(view, thrift_string_size_limit=MAX_BYTES,
                              thrift_container_size_limit=10000, arrow_extensions_enabled=False).metadata
    return metadata, metadata.schema.to_arrow_schema()


def metadata(source):
    from files_reader import arrow_kind
    with stable_file(source) as opened:
        path, handle = opened
        if source.get('format') in ('csv', 'tsv'):
            names = next(csv.reader(header_lines(handle), delimiter='\t' if source['format'] == 'tsv' else ',', strict=True), None)
            names_valid(names)
            columns = [{'name': name, 'type':'string', 'nullable':True} for name in names]
        elif source.get('format') == 'parquet':
            _, schema = parquet_metadata(handle)
            names_valid(schema.names)
            columns = []
            for field in schema:
                kind = arrow_kind(field.type)
                column = {'name':field.name, 'type':kind, 'nullable':field.nullable}
                if kind == 'decimal':
                    require(1 <= field.type.precision <= 38 and 0 <= field.type.scale <= field.type.precision, 'ACCESS_UNSUPPORTED')
                    column.update(precision=field.type.precision, scale=field.type.scale)
                columns.append(column)
        else:
            raise AccessError('SAMPLING_REQUIRED')
    return object_entry(source, path.name, 'file', columns)


def document_tokens(value, depth=0):
    """JSON text keeps nested decimal and large integer tokens exact."""
    require(depth <= 32, 'SAMPLE_VALUE')
    if isinstance(value, dict):
        yield '{'
        for index, (key, item) in enumerate(value.items()):
            if index: yield ','
            yield json.dumps(key, ensure_ascii=False) + ':'
            yield from document_tokens(item, depth + 1)
        yield '}'
    elif isinstance(value, list):
        yield '['
        for index, item in enumerate(value):
            if index: yield ','
            yield from document_tokens(item, depth + 1)
        yield ']'
    elif isinstance(value, Decimal):
        require(value.is_finite(), 'SAMPLE_VALUE')
        yield str(value)
    else:
        yield json.dumps(value, ensure_ascii=False, allow_nan=False)


def document_cell(value):
    if not isinstance(value, (dict, list)):
        return cell(value), False
    text = ''
    for token in document_tokens(value):
        text += token
        if len(text.encode('utf-16-le')) > MAX_CELL * 2:
            suffix = '… (truncated)'
            return text.encode('utf-16-le')[:(MAX_CELL-len(suffix))*2].decode('utf-16-le', errors='ignore') + suffix, True
    return text, False


def json_sample(request):
    # The shared prefix reader enforces file identity, byte, row and field bounds.
    _, records, more = prefix(request['source'], request.get('limit', 20), max_fields=500)
    names = list(records[0]); names_valid(names)
    chosen = selection(names, request.get('columns'))
    rows = []
    for record in records:
        row = []
        for name in chosen:
            value, shortened = document_cell(record[name])
            row.append(value); more = more or shortened
        rows.append(row)
    result = {'columns': chosen, 'rows': rows, 'truncated': more}
    while len(json.dumps(result).encode()) > 500_000 and result['rows']:
        result['rows'].pop(); result['truncated'] = True
    return result


def sample(request):
    limit, requested = request.get('limit', 20), request.get('columns')
    require(type(limit) is int and 1 <= limit <= 50, 'SAMPLE_LIMIT')
    if requested is not None:
        require(isinstance(requested, list) and 1 <= len(requested) <= 100
                and all(isinstance(name, str) and 1 <= len(name) <= 128 for name in requested)
                and len(set(requested)) == len(requested), 'SAMPLE_COLUMNS')
    source = request['source']
    if source.get('format') in ('json', 'jsonl'):
        return json_sample(request)
    require(source.get('format') in ('csv', 'tsv', 'parquet'), 'SAMPLE_FORMAT')
    rows, more = [], False
    with stable_file(source) as opened:
        _, handle = opened
        counted = BudgetReader(handle)
        if source['format'] in ('csv', 'tsv'):
            csv.field_size_limit(MAX_BYTES)
            with io.TextIOWrapper(io.BufferedReader(counted), encoding='utf-8-sig', newline='') as text:
                records = csv.reader(text, delimiter='\t' if source['format'] == 'tsv' else ',', strict=True)
                names = next(records, None); names_valid(names); chosen = selection(names, requested)
                indices = [names.index(name) for name in chosen]
                for values in records:
                    require(len(values) == len(names), 'SAMPLE_SHAPE')
                    if len(rows) == limit:
                        more = True; break
                    rows.append([cell(values[index] if values[index] != '' else None) for index in indices])
        else:
            import pyarrow as pa
            import pyarrow.parquet as pq
            from files_reader import arrow_kind
            info, schema = parquet_metadata(counted)
            names_valid(schema.names); chosen = selection(schema.names, requested)
            for name in chosen: arrow_kind(schema.field(name).type)
            groups, available, uncompressed = [], 0, 0
            for index in range(info.num_row_groups):
                group = info.row_group(index)
                if group.num_rows == 0: continue
                for name in chosen:
                    columns = [group.column(i) for i in range(group.num_columns) if group.column(i).path_in_schema == name]
                    require(len(columns) == 1, 'SAMPLE_COLUMNS')
                    require(columns[0].total_uncompressed_size >= 0, 'SAMPLE_SHAPE')
                    uncompressed += columns[0].total_uncompressed_size
                require(uncompressed <= MAX_UNCOMPRESSED, 'SAMPLE_TOO_LARGE')
                groups.append(index); available += group.num_rows
                if available >= limit + 1: break
            try:
                file = pq.ParquetFile(counted, metadata=info, memory_map=False, pre_buffer=False,
                                      buffer_size=0, arrow_extensions_enabled=False)
                for batch in file.iter_batches(batch_size=limit + 1, row_groups=groups, columns=chosen, use_threads=False):
                    for record in batch.to_pylist():
                        if len(rows) == limit:
                            more = True; break
                        rows.append([cell(record[name]) for name in chosen])
                    if more: break
            except Exception:
                if counted.exceeded: raise AccessError('SAMPLE_TOO_LARGE')
                raise
    result = {'columns':chosen, 'rows':rows, 'truncated':more}
    while len(json.dumps(result).encode()) > 500_000 and result['rows']:
        result['rows'].pop(); result['truncated'] = True
    return result
