"""Read-only source methods for the custom starter. Metadata reads sidecar schemas."""
import hashlib
import json
import os
from pathlib import Path
import sys
import __MODULE___runtime as runtime
from source_sample import cell, selected, SampleError


def entry(source, columns=None):
    identity = hashlib.sha256(json.dumps(source, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16]
    return {'id': 'table_' + identity, 'name': source['path'], 'source': source, 'kind': 'file',
            **({'columns': columns} if columns is not None else {})}


def execute(request):
    action = request.get('action')
    result = {'apiVersion': 'ingestron.source-access-result/v1', 'action': action,
              'status': 'succeeded', 'scope': 'connection' if action == 'test' else 'data' if action == 'sample' else 'metadata', 'tables': []}
    try:
        if request.get('connector') != '__ID__' or action not in ('test', 'inventory', 'metadata', 'sample'):
            runtime.fail('ACCESS_INPUT')
        settings = runtime.connector.settings(request.get('settings'))
        if action == 'test':
            with os.scandir(runtime.folder(settings)) as items: next(items, None)
        elif action == 'inventory':
            limit, query, cursor = request.get('limit', 50), request.get('query', ''), request.get('cursor', '')
            if type(limit) is not int or not 1 <= limit <= 200 or not isinstance(query, str) or len(query) > 128 or not isinstance(cursor, str) or len(cursor) > 255:
                runtime.fail('ACCESS_INPUT')
            names = []
            with os.scandir(runtime.folder(settings)) as items:
                for index, item in enumerate(items):
                    if index >= 10000: runtime.fail('ACCESS_TOO_LARGE')
                    if item.is_file(follow_symlinks=False) and item.name.endswith('.jsonl') and query.casefold() in item.name.casefold() and item.name > cursor:
                        names.append(item.name)
            names.sort()
            result['tables'] = [entry({'path': name}) for name in names[:limit]]
            if len(names) > limit: result['nextCursor'] = names[limit - 1]
        elif action == 'metadata':
            tables = request.get('tables')
            if not isinstance(tables, list) or not 1 <= len(tables) <= 100: runtime.fail('ACCESS_INPUT')
            result['tables'] = [entry(source, runtime.connector.catalogue(settings, source)) for source in tables]
        else:
            limit = request.get('limit', 20)
            if type(limit) is not int or not 1 <= limit <= 50: raise SampleError('SAMPLE_LIMIT')
            source = request.get('source', {})
            declaration = runtime.schema(settings, source)
            fields = selected(runtime.connector.catalogue(settings, source), request)
            rows, truncated = [], False
            for row in runtime.records(settings, source, declaration):
                if len(rows) == limit:
                    truncated = True
                    break
                rows.append([cell(row.get(c['name'])) for c in fields])
            sample = {'columns': [c['name'] for c in fields], 'rows': rows, 'truncated': truncated}
            while len(json.dumps(sample).encode()) > 500_000 and rows:
                rows.pop(); sample['truncated'] = True
            result['sample'] = sample
    except Exception as error:
        code = getattr(error, 'code', 'ACCESS_FAILED')
        allowed = set(runtime.connector.errors) | {'ACCESS_INPUT', 'ACCESS_TOO_LARGE', 'ACCESS_FAILED', 'SAMPLE_LIMIT', 'SAMPLE_COLUMNS', 'SAMPLE_VALUE'}
        result.update(status='failed', code=code if code in allowed else 'ACCESS_FAILED', tables=[])
        result.pop('sample', None); result.pop('nextCursor', None)
    return result


if __name__ == '__main__':
    try:
        file = Path(sys.argv[1])
        if file.stat().st_size > 1_000_000: runtime.fail('ACCESS_INPUT')
        result = execute(json.loads(file.read_text()))
    except Exception:
        result = {'apiVersion': 'ingestron.source-access-result/v1', 'action': 'test', 'status': 'failed', 'scope': 'connection', 'tables': [], 'code': 'ACCESS_INPUT'}
    print(json.dumps(result))
