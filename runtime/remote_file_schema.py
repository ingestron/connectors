"""Explicit bounded JSON schema suggestions for selected remote files.

Transport remains in source_sample and the connector readers. Suggestions carry
only field metadata and sampling evidence; temporary local paths and record values
never leave this method. Other source actions preserve their existing behaviour.
"""
import re
from source_access import AccessError, execute as original_execute, object_entry, secret

KINDS = ('s3', 'gcs', 'azure-blob', 'sftp', 'sharepoint', 'onedrive')


def require(value, code='ACCESS_INPUT'):
    if not value: raise AccessError(code)


def execute(request):
    kind = request.get('connector')
    if kind not in KINDS or request.get('action') != 'metadata':
        return original_execute(request)
    response = {'apiVersion':'ingestron.source-access-result/v1', 'action':'metadata',
                'status':'succeeded', 'scope':'metadata', 'tables':[]}
    try:
        options = request.get('options')
        if 'options' in request:
            require(isinstance(options,dict) and set(options) <= {'sampleRecords','limit'})
            require(options.get('sampleRecords') is True)
            require(type(options.get('limit',20)) is int and 1 <= options.get('limit',20) <= 50)
        sources = request['tables']
        require(isinstance(sources,list) and 1 <= len(sources) <= 100 and all(isinstance(source,dict) for source in sources))
        # Consent and input checks precede every source request, including mixed selections.
        require(not any(source.get('format') in ('json','jsonl') and
                        not (kind == 'sharepoint' and source.get('entity') == 'list')
                        for source in sources) or options is not None, 'SAMPLING_REQUIRED')
        settings = secret(request['settings'])
        from source_sample import remote_file_read
        from source_access import file_metadata
        from files_schema_sample import schema_sample
        for source in sources:
            if kind == 'sharepoint' and source.get('entity') == 'list':
                from graph_reader import list_catalogue, list_name
                entry = object_entry(source,list_name(source['path']),'object',list_catalogue(settings,source))
            elif source.get('format') in ('json','jsonl'):
                sampled = remote_file_read(kind,settings,source,lambda local: schema_sample(local,options))
                entry = object_entry(source,source['path'].rsplit('/',1)[-1],'file',sampled['columns'])
                entry['sampling'] = sampled['sampling']
                response['scope'] = 'data'
            else:
                info = remote_file_read(kind,settings,source,file_metadata)
                entry = object_entry(source,source['path'].rsplit('/',1)[-1],'file',info['columns'])
            response['tables'].append(entry)
    except Exception as error:
        code = getattr(error,'code','ACCESS_FAILED')
        if not isinstance(code,str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{2,40}',code): code='ACCESS_FAILED'
        response.update(status='unsupported' if code == 'SAMPLING_REQUIRED' else 'failed',code=code,tables=[])
    return response
