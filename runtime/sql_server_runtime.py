"""Multi-table SQL snapshots through the reviewed local execution boundary."""
import connector_kit as kit
from sql_server_reader import scan as read_sql, SQLSourceError


class SqlServer(kit.TableConnector):
    name = 'SQL'
    table_keys = frozenset({'schema', 'table'})
    errors = {
        'SQL_CONNECT': 'Cannot connect to SQL. Check network access, credentials and TLS. If the database was paused, wait for it to resume before retrying.',
        'SQL_READ': 'SQL read failed. Check table permissions and source availability.',
        'SQL_TABLE': 'SQL table is absent or its metadata is not visible. Check schema, table and metadata permissions.',
    }

    def settings(self, settings):
        kit.workflow.check(set(settings) == {'connection'},
                           'SQL connection settings must contain only connection')
        return settings

    def table(self, source, columns):
        return {'schema': source['schema'], 'table': source['table'],
                'columns': [column['name'] for column in columns]}

    def __init__(self, connect=None):
        # Tests and container checks may supply the driver's connect function.
        self.connect = connect

    def scan(self, settings, table, emit=None):
        extra = {'connect': self.connect} if self.connect else {}
        schema, _ = scan({'connection': settings['connection'], 'object': table}, emit, **extra)
        return schema


def scan(*args, **kwargs):
    try:
        return read_sql(*args, **kwargs)
    except SQLSourceError as error:
        raise kit.SourceError(error.code) from None


connector = SqlServer()
workflow = kit.install(connector)
source_config, sql_output, sql_review = connector.source_config, connector.output, connector.review
runtime_identity = workflow.runtime_identity

if __name__ == '__main__':
    workflow.main()
