"""Stripe objects through the connector kit (PB-064 phase 4, preview)."""
import connector_kit as kit
import stripe_reader as reader

KINDS = {'STRING': 'string', 'BIGINT': 'integer', 'INT': 'integer', 'INTEGER': 'integer',
         'BOOLEAN': 'boolean'}


class Stripe(kit.TableConnector):
    name = 'Stripe'
    table_keys = frozenset({'object'})
    errors = reader.ERRORS

    def settings(self, settings):
        kit.workflow.check(set(settings) == {'api_key'},
                           'Stripe connection settings must contain only api_key')
        reader.api_key(settings)
        return settings

    def table(self, source, columns):
        catalogue = reader.fields(source['object'])
        for column in columns:
            kind = KINDS.get(column['type'].upper())
            kit.workflow.check(column['name'] in catalogue,
                               'Select only documented top-level Stripe fields for this object')
            kit.workflow.check(kind == catalogue[column['name']],
                               'Contract type differs from the Stripe field type')
        return {'object': source['object'], 'columns': [column['name'] for column in columns]}

    def scan(self, settings, table, emit=None):
        try:
            return reader.scan(settings, table, emit)
        except reader.StripeError as error:
            raise kit.SourceError(error.code) from None

    def catalogue(self, settings, source):
        try:
            return reader.catalogue(settings, source['object'])
        except reader.StripeError as error:
            raise kit.SourceError(error.code) from None


connector = Stripe()
workflow = kit.install(connector)
source_config, stripe_output, stripe_review = connector.source_config, connector.output, connector.review
runtime_identity = workflow.runtime_identity
if __name__ == '__main__': workflow.main()
