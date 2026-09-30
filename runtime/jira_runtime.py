"""Jira through the connector kit (PB-064 phase 7, preview)."""
import connector_kit as kit
import jira_reader as reader
from rest_client import ApiError, kind_of


class Jira(kit.TableConnector):
    name = 'Jira'
    table_keys = frozenset({'object'})
    optional_keys = frozenset({'jql'})
    errors = reader.ERRORS

    def settings(self, settings):
        keys = {'site', 'email', 'api_token'}
        kit.workflow.check(set(settings) == keys, 'Jira connection settings must contain only ' + ', '.join(sorted(keys)))
        reader.settings_for(settings)
        return settings

    def table(self, source, columns):
        kit.workflow.check(source['object'] in reader.OBJECTS,
                           'object must be one of ' + ', '.join(reader.OBJECTS))
        kit.workflow.check('jql' not in source or (source['object'] == 'issues' and isinstance(source['jql'], str)
                                                   and 0 < len(source['jql']) <= 2000),
                           'jql applies to the issues table only')
        return {**source, 'columns': [c['name'] for c in columns],
                'kinds': {c['name']: kind_of(c['type']) for c in columns}}

    def scan(self, settings, table, emit=None):
        try:
            return reader.scan(settings, table, emit)
        except ApiError as error:
            raise kit.SourceError(error.code) from None

    def catalogue(self, settings, source):
        try:
            return reader.catalogue(settings, source['object'])
        except ApiError as error:
            raise kit.SourceError(error.code) from None


connector = Jira()
workflow = kit.install(connector)
source_config, api_output, api_review = connector.source_config, connector.output, connector.review
runtime_identity = workflow.runtime_identity
if __name__ == '__main__': workflow.main()
