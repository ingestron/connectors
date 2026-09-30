"""Salesforce objects through the connector kit (PB-064 phase 7, preview)."""
import connector_kit as kit
import salesforce_reader as reader
from rest_client import ApiError, kind_of


class Salesforce(kit.TableConnector):
    name = 'Salesforce'
    table_keys = frozenset({'object'})
    errors = reader.ERRORS

    def settings(self, settings):
        kit.workflow.check(set(settings) == {'instance_url', 'client_id', 'client_secret'},
                           'Salesforce connection settings must contain only instance_url, client_id and client_secret')
        reader.settings_for(settings)
        return settings

    def table(self, source, columns):
        kit.workflow.check(reader.OBJECT.fullmatch(source['object']) is not None,
                           'object must be a Salesforce object API name such as Account or Invoice__c')
        kit.workflow.check(all(reader.FIELD.fullmatch(c['name']) for c in columns),
                           'Contract columns must be Salesforce field API names')
        return {'object': source['object'], 'columns': [c['name'] for c in columns],
                'kinds': {c['name']: kind_of(c['type']) for c in columns}}

    def scan(self, settings, table, emit=None):
        try:
            return reader.scan(settings, table, emit)
        except ApiError as error:
            raise kit.SourceError(error.code) from None


connector = Salesforce()
workflow = kit.install(connector)
source_config, sf_output, sf_review = connector.source_config, connector.output, connector.review
runtime_identity = workflow.runtime_identity
if __name__ == '__main__': workflow.main()
