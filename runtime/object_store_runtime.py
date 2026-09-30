"""Amazon S3 and Google Cloud Storage objects through the connector kit (PB-064 phase 7)."""
import connector_kit as kit
import object_store_reader as reader
from files_reader import parser_kind

LABELS = {'s3': ('S3', 'Amazon S3'), 'gcs': ('GCS', 'Google Cloud Storage')}
REQUIRED = {'bucket', 'access_key_id', 'secret_access_key'}
OPTIONAL = {'s3': {'region', 'session_token', 'endpoint'}, 'gcs': set()}


class ObjectStore(kit.TableConnector):
    table_keys = frozenset({'path', 'format'})

    def __init__(self, kind):
        self.kind = kind
        self.prefix, self.name = LABELS[kind]
        self.errors = reader.errors(self.prefix, self.name)

    def settings(self, settings):
        keys = set(settings)
        needed = REQUIRED | ({'region'} if self.kind == 's3' else set())
        kit.workflow.check(needed <= keys <= REQUIRED | OPTIONAL[self.kind],
                           f'{self.name} connection settings: ' + ', '.join(sorted(needed | OPTIONAL[self.kind])))
        reader.endpoint(settings, self.kind)
        return settings

    def table(self, source, columns):
        kit.workflow.check(source['format'] in reader.SUFFIX, 'Choose csv, tsv, json, jsonl or parquet')
        return {'path': reader.table_path(source['path']), 'format': source['format'],
                'types': {column['name']: parser_kind(column['type']) for column in columns}}

    def scan(self, settings, table, emit=None):
        try:
            return reader.scan(self.prefix, settings, self.kind, table, emit)
        except reader.StoreError as error:
            raise kit.SourceError(error.code) from None


def install(kind):
    connector = ObjectStore(kind)
    return connector, kit.install(connector)
