"""SharePoint and OneDrive files through Microsoft Graph and the connector kit (PB-064 phase 4, preview)."""
import connector_kit as kit
import graph_reader as reader
from files_reader import parser_kind

KEYS = {'sharepoint': {'tenant_id', 'client_id', 'client_secret', 'site'},
        'onedrive': {'tenant_id', 'client_id', 'client_secret', 'user'}}


class GraphFiles(kit.TableConnector):
    table_keys = frozenset({'path'})
    # Files name a format; SharePoint lists use entity: list, as on the native routes.
    optional_keys = frozenset({'format', 'entity'})
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
        entity = source.get('entity', 'file')
        kit.workflow.check(entity in ('file', 'list') and (self.kind == 'sharepoint' or entity == 'file'),
                           'entity must be file, or list for SharePoint')
        types = {column['name']: parser_kind(column['type']) for column in columns}
        if entity == 'list':
            kit.workflow.check('format' not in source, 'format applies to files only')
            reader.list_name(source['path'])
            return {'path': source['path'], 'entity': 'list', 'types': types}
        kit.workflow.check(source.get('format') in reader.SUFFIX, 'Files need a format')
        return {'path': reader.table_path(source['path'], self.kind), 'format': source['format'],
                'types': types}

    def scan(self, settings, table, emit=None):
        try:
            return reader.scan(settings, self.kind, table, emit)
        except reader.GraphError as error:
            raise kit.SourceError(error.code) from None


def install(kind):
    connector = GraphFiles(kind)
    workflow = kit.install(connector)
    return connector, workflow
