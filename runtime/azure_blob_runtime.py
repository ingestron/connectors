"""Several contracted Azure Blob or ADLS Gen2 files through the reviewed snapshot workflow."""
import connector_kit as kit
from azure_blob_reader import endpoint, blob_path, scan
from files_reader import parser_kind


class AzureBlob(kit.TableConnector):
    name = 'Azure Blob'
    table_keys = frozenset({'path', 'format'})

    def settings(self, settings):
        kit.workflow.check(set(settings) == {'account', 'container', 'sas_token'},
                           'Azure Blob connection settings must contain only account, container and sas_token')
        endpoint(settings)
        return settings

    def table(self, source, columns):
        return {'path': blob_path(source['path']), 'format': source['format'],
                'types': {column['name']: parser_kind(column['type']) for column in columns}}

    def scan(self, settings, table, emit=None):
        schema, _ = scan(settings, table, emit)
        return schema

    def catalogue(self, settings, source):
        # Infer from the data itself; text columns get suggested types from a sample.
        schema, rows = kit.sampled(lambda emit: self.scan(settings, self.table(source, []), emit))
        return kit.columns_from_schema(schema, rows)


connector = AzureBlob()
workflow = kit.install(connector)
source_config, blob_output, blob_review = connector.source_config, connector.output, connector.review
runtime_identity = workflow.runtime_identity
if __name__ == '__main__': workflow.main()
