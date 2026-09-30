# Salesforce objects

Reads Salesforce objects into reviewed local snapshots through the REST API. One connection names the org and connected app; each table names an object, and its contract selects fields by API name. It only reads.

| Package  | `salesforce@0.1.0`                                              |
| -------- | --------------------------------------------------------------- |
| Kind     | `salesforce`                                                    |
| Maturity | preview: conformance suite against a mock of the documented API |
| Licence  | Adapter Apache-2.0; HTTPS through the Python standard library   |
| Cost     | No Ingestron charge; Salesforce API limits apply                |

## Install

```sh
ingestron connector install salesforce@0.1.0
```

## Connection

Create a connected app with the [client credentials flow](https://help.salesforce.com/s/articleView?id=sf.connected_app_client_credentials_setup.htm) and an integration user with API access and read access to the objects. A Developer Edition org is free. Keep the client secret in an environment variable referenced with `$secret`.

```yaml
connections:
  source:
    package: salesforce
    sourceId: source
    tenantId: training
    settings:
      instance_url: https://acme.my.salesforce.com
      client_id: 3MVG9EXAMPLE
      client_secret:
        $secret:
          env: SALESFORCE_CLIENT_SECRET
flows:
  - apiVersion: ingestron.flow/v1
    kind: ingestion
    id: source_local
    provider: local
    ingestion:
      connection: source
      execution: { mode: local }
    tables:
      accounts:
        source: { object: Account }
        contract: { $resolve: ./contracts/accounts.odcs.yaml }
```

## Tables

| `source` key | Meaning                                            |
| ------------ | -------------------------------------------------- |
| `object`     | Object API name, such as `Account` or `Invoice__c` |

## Types

Field types come from the object describe: `int` and `long` are integers, `double`, `currency` and `percent` numbers, `boolean` booleans, and everything else (including dates, IDs and references) text. The contract must match; a mismatch fails as `SF_SCHEMA`.

## Behaviour and limits

Discovery reads the object describe; a run issues one SOQL query of the contract fields and follows `nextRecordsUrl` pages. API version v62.0. Reads are full snapshots of up to one million records; deleted records are excluded. Errors name a code (`SF_AUTH`, `SF_FORBIDDEN`, `SF_NOT_FOUND`, `SF_RATE_LIMIT`, `SF_SCHEMA` and others) and never include secrets or record values.

## Evidence

The shared conformance suite and unit tests pass against a mock that follows the documented token, describe and query responses. No live org has been used, so the connector is a preview. The same object names work on the ADF and Databricks native routes.

## References

- [REST API developer guide](https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/)
- [Query resource](https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_query.htm)
