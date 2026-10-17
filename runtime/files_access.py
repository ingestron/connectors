"""Bounded local folder inventory. No records are read while browsing."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from source_access import AccessError, execute as source_execute, object_entry

FORMATS = ('csv', 'tsv', 'json', 'jsonl', 'parquet')
MAX_ENTRIES = 10000


def require(value, code='ACCESS_INPUT'):
    if not value:
        raise AccessError(code)


def open_folder(value):
    require(isinstance(value, str) and 1 <= len(value) <= 4000)
    path = Path(value)
    require(path.is_absolute() and '..' not in path.parts)
    # Listing needs read permission on the selected folder, not every ancestor.
    # Check ancestors for symlinks and compare the opened folder with its path.
    require(not any(parent.is_symlink() for parent in [path, *path.parents]))
    before = path.stat(follow_symlinks=False)
    require(stat.S_ISDIR(before.st_mode))
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(descriptor)
        require((before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino), 'ACCESS_CHANGED')
        return path, descriptor
    except Exception:
        os.close(descriptor)
        raise


def folder_inventory(request):
    scope = request.get('scope')
    require(isinstance(scope, dict) and set(scope) <= {'directory', 'format'})
    fmt = scope.get('format', 'all')
    require(fmt == 'all' or fmt in FORMATS)
    query = request.get('query', '')
    limit = request.get('limit', 50)
    require(isinstance(query, str) and len(query) <= 128)
    require(type(limit) is int and 1 <= limit <= 200)
    require(not request.get('schema'))
    path, descriptor = open_folder(scope.get('directory'))
    try:
        before = os.fstat(descriptor)
        identity = hashlib.sha256(json.dumps(
            [str(path), before.st_dev, before.st_ino, query, fmt],
            separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
        after_name = ''
        if request.get('cursor'):
            cursor = json.loads(request['cursor'])
            require(isinstance(cursor, dict) and set(cursor) == {'v', 'scope', 'after'})
            require(type(cursor['v']) is int and cursor['v'] == 1 and cursor['scope'] == identity)
            after_name = cursor['after']
            require(isinstance(after_name, str) and 1 <= len(after_name) <= 300)
            require('/' not in after_name and '\\' not in after_name)
        names = []
        with os.scandir(descriptor) as entries:
            for count, entry in enumerate(entries, 1):
                require(count <= MAX_ENTRIES, 'ACCESS_TOO_LARGE')
                name = entry.name
                extension = Path(name).suffix.lower().lstrip('.')
                if (extension not in FORMATS or (fmt != 'all' and extension != fmt)
                        or query.casefold() not in name.casefold() or name <= after_name):
                    continue
                require(len(name) <= 300, 'ACCESS_TOO_LARGE')
                if not stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode):
                    continue
                names.append((name, extension))
        after = os.fstat(descriptor)
        current = path.stat(follow_symlinks=False)
        stamp = lambda info: (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns)
        require(stamp(before) == stamp(after) == stamp(current) and not any(parent.is_symlink() for parent in path.parents), 'ACCESS_CHANGED')
        names.sort()
        tables = [object_entry({'path': str(path / name), 'format': extension}, name, 'file')
                  for name, extension in names[:limit]]
        cursor = json.dumps({'v': 1, 'scope': identity, 'after': names[limit - 1][0]},
                            separators=(',', ':')) if len(names) > limit else None
        return tables, cursor
    finally:
        os.close(descriptor)


def execute(request):
    if (request.get('connector') == 'files' and request.get('action') == 'sample'
            and isinstance(request.get('source'), dict)):
        response = {'apiVersion': 'ingestron.source-access-result/v1', 'action': 'sample',
                    'status': 'succeeded', 'scope': 'data', 'tables': []}
        try:
            require(request.get('settings') == {})
            from files_data_sample import sample
            response['sample'] = sample(request)
        except Exception as error:
            code = getattr(error, 'code', 'ACCESS_FORBIDDEN' if isinstance(error, PermissionError) else 'ACCESS_FAILED')
            response.update(status='failed', code=code)
            response.pop('sample', None)
        return response
    if request.get('connector') == 'files' and request.get('action') == 'metadata':
        response = {'apiVersion': 'ingestron.source-access-result/v1', 'action': 'metadata',
                    'status': 'succeeded', 'scope': 'metadata', 'tables': []}
        try:
            options = request.get('options')
            require(request.get('settings') == {})
            if 'options' in request:
                require(isinstance(options, dict) and set(options) <= {'sampleRecords', 'limit'})
                require(options.get('sampleRecords') is True)
                require(type(options.get('limit', 20)) is int and 1 <= options.get('limit', 20) <= 50)
            sources = request['tables']
            require(isinstance(sources, list) and 1 <= len(sources) <= 100)
            from files_data_sample import metadata as file_metadata
            from files_schema_sample import schema_sample
            for source in sources:
                if source.get('format') in ('json', 'jsonl'):
                    require(options is not None, 'SAMPLING_REQUIRED')
                    response['tables'].append(schema_sample(source, options))
                    response['scope'] = 'data'
                else:
                    response['tables'].append(file_metadata(source))
        except Exception as error:
            code = error.code if isinstance(error, AccessError) else 'ACCESS_FORBIDDEN' if isinstance(error, PermissionError) else 'ACCESS_FAILED'
            response.update(status='unsupported' if code in ('SAMPLING_REQUIRED', 'ACCESS_UNSUPPORTED') else 'failed', code=code, tables=[])
        return response
    if request.get('connector') != 'files' or request.get('action') != 'inventory':
        return source_execute(request)
    response = {'apiVersion': 'ingestron.source-access-result/v1', 'action': 'inventory',
                'status': 'succeeded', 'scope': 'file', 'tables': []}
    try:
        require(request.get('settings') == {})
        response['tables'], cursor = folder_inventory(request)
        if cursor:
            response['nextCursor'] = cursor
    except Exception as error:
        code = error.code if isinstance(error, AccessError) else 'ACCESS_FORBIDDEN' if isinstance(error, PermissionError) else 'ACCESS_FAILED'
        response.update(status='failed', code=code, tables=[])
        response.pop('nextCursor', None)
    return response


if __name__ == '__main__':
    try:
        path = Path(sys.argv[1])
        require(path.stat().st_size <= 1000000, 'ACCESS_TOO_LARGE')
        result = execute(json.loads(path.read_text()))
    except Exception:
        result = {'apiVersion': 'ingestron.source-access-result/v1', 'action': 'inventory',
                  'status': 'failed', 'scope': 'file', 'tables': [], 'code': 'ACCESS_FAILED'}
    print(json.dumps(result, allow_nan=False))
