"""PostgreSQL, MySQL and Oracle tables through the connector kit (PB-064 phase 3)."""
import connector_kit as kit
from dbapi_reader import DIALECTS, DatabaseSourceError, connection_settings, scan


class Database(kit.TableConnector):
    table_keys = frozenset({'schema', 'table'})

    def __init__(self, dialect, connect=None):
        self.dialect = dialect
        self.name = DIALECTS[dialect]['label']
        label = self.name
        self.errors = {
            'DB_CONNECT': f'Cannot connect to {label}. Check network access, credentials and TLS.',
            'DB_READ': f'{label} read failed. Check table permissions and source availability.',
            'DB_TABLE': f'{label} table is absent or its metadata is not visible. Check schema, table and permissions.',
        }
        # Tests and container checks may supply the driver's connect function.
        self.connect = connect

    def settings(self, settings):
        kit.workflow.check(set(settings) == {'connection'},
                           f'{self.name} connection settings must contain only connection')
        return {'connection': connection_settings(self.dialect, settings['connection'])}

    def table(self, source, columns):
        return {'schema': source['schema'], 'table': source['table'],
                'columns': [column['name'] for column in columns]}

    def scan(self, settings, table, emit=None):
        try:
            schema, _ = scan(self.dialect, settings['connection'], table, emit, self.connect)
        except DatabaseSourceError as error:
            raise kit.SourceError(error.code) from None
        return schema


def install(dialect):
    connector = Database(dialect)
    workflow = kit.install(connector)
    return connector, workflow
