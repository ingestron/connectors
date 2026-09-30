"""SharePoint and OneDrive files through Microsoft Graph and the connector kit (PB-064 phase 4, preview)."""
import connector_kit as kit
import graph_reader as reader
from files_reader import parser_kind

KEYS = {'sharepoint': {'tenant_id', 'client_id', 'client_secret', 'site'},
        'onedrive': {'tenant_id', 'client_id', 'client_secret', 'user'}}


class GraphFiles(kit.TableConnector):
    table_keys = frozenset({'path', 'format'})
    errors = reader.ERRORS

    def __init__(self, kind):
        self.kind = kind
        self.name = 'SharePoint' if kind == 'sharepoint' else 'OneDrive'

    def settings(self, settings):
        kit.workflow.check(set(settings) == KEYS[self.kind],
                           f'{self.name} connection settings must contain only ' + ', '.join(sorted(KEYS[self.kind])))
        reader.settings_for(settings, self.kind)
        return settings

    def table(self, source, columns):
        return {'path': reader.table_path(source['path'], self.kind), 'format': source['format'],
                'types': {column['name']: parser_kind(column['type']) for column in columns}}

    def scan(self, settings, table, emit=None):
        try:
            return reader.scan(settings, self.kind, table, emit)
        except reader.GraphError as error:
            raise kit.SourceError(error.code) from None


def install(kind):
    connector = GraphFiles(kind)
    workflow = kit.install(connector)
    return connector, workflow
