"""Several contracted local files through the reviewed snapshot workflow."""
import connector_kit as kit
from files_reader import scan, parser_kind


class Files(kit.TableConnector):
    name = 'File'
    table_keys = frozenset({'path', 'format'})

    def settings(self, settings):
        kit.workflow.check(settings == {}, 'Local file connection settings must be empty')
        return settings

    def table(self, source, columns):
        return {'path': source['path'], 'format': source['format'],
                'types': {column['name']: parser_kind(column['type']) for column in columns}}

    def scan(self, settings, table, emit=None):
        schema, _ = scan(table, emit)
        return schema

    def catalogue(self, settings, source):
        # Infer from the data itself; text columns get suggested types from a sample.
        schema, rows = kit.sampled(lambda emit: self.scan(settings, self.table(source, []), emit))
        return kit.columns_from_schema(schema, rows)


connector = Files()
workflow = kit.install(connector)
source_config, file_output, file_review = connector.source_config, connector.output, connector.review
runtime_identity = workflow.runtime_identity
if __name__ == '__main__': workflow.main()
