"""SFTP files through the connector kit (PB-064 phase 7)."""
import connector_kit as kit
import sftp_reader as reader
from files_reader import parser_kind


class Sftp(kit.TableConnector):
    name = 'SFTP'
    table_keys = frozenset({'path', 'format'})
    errors = reader.ERRORS

    def __init__(self, transport=None):
        # Tests supply a transport; the runtime uses the system OpenSSH client.
        self.transport = transport

    def settings(self, settings):
        kit.workflow.check({'host', 'user', 'private_key', 'host_key'} <= set(settings)
                           <= {'host', 'port', 'user', 'private_key', 'host_key'},
                           'SFTP connection settings: host, port, user, private_key and host_key')
        reader.settings_for(settings)
        return settings

    def table(self, source, columns):
        kit.workflow.check(source['format'] in reader.SUFFIX, 'Choose csv, tsv, json, jsonl or parquet')
        return {'path': reader.table_path(source['path']), 'format': source['format'],
                'types': {column['name']: parser_kind(column['type']) for column in columns}}

    def scan(self, settings, table, emit=None):
        try:
            return reader.scan(settings, table, emit, self.transport)
        except reader.SftpError as error:
            raise kit.SourceError(error.code) from None

    def catalogue(self, settings, source):
        # Infer from the data itself; text columns get suggested types from a sample.
        schema, rows = kit.sampled(lambda emit: self.scan(settings, self.table(source, []), emit))
        return kit.columns_from_schema(schema, rows)


connector = Sftp()
workflow = kit.install(connector)
source_config, sftp_output, sftp_review = connector.source_config, connector.output, connector.review
runtime_identity = workflow.runtime_identity
if __name__ == '__main__': workflow.main()
