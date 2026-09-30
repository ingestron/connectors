# HubSpot CRM objects

Reads HubSpot CRM objects into reviewed local snapshots through the CRM v3 API. One connection holds a private app token; each table names an object, and its contract selects properties. It only reads.

| Package  | `hubspot@0.1.0`                                                 |
| -------- | --------------------------------------------------------------- |
| Kind     | `hubspot`                                                       |
| Maturity | preview: conformance suite against a mock of the documented API |
| Licence  | Adapter Apache-2.0; HTTPS through the Python standard library   |
| Cost     | No Ingestron charge; HubSpot API limits apply                   |

## Install

```sh
ingestron connector install hubspot@0.1.0
```

## Connection

Create a [private app](https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/overview) with read scopes for the objects. Keep the token in an environment variable referenced with `$secret`.

```yaml
connections:
  source:
    package: hubspot
    sourceId: source
    tenantId: training
    settings:
      access_token:
        $secret:
          env: HUBSPOT_TOKEN
flows:
  - apiVersion: ingestron.flow/v1
    kind: ingestion
    id: source_local
    provider: local
    ingestion:
      connection: source
      execution: { mode: local }
    tables:
      contacts:
        source: { object: contacts }
        contract: { $resolve: ./contracts/contacts.odcs.yaml }
```

## Tables

| `source` key | Meaning                                                                                                                                                                             |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `object`     | `calls`, `companies`, `contacts`, `deals`, `emails`, `leads`, `line_items`, `meetings`, `notes`, `orders`, `products`, `tasks` or `tickets`, the names used by the Databricks route |

## Types

Columns are property names plus `id`, `createdAt`, `updatedAt` and `archived`. HubSpot returns property values as text; `number` properties are converted to the contracted integer or decimal, `bool` to booleans, and the rest stay text.

## Behaviour and limits

Discovery reads the object's properties; a run pages through the objects API with the `after` cursor, 100 records at a time, and fails if a cursor repeats. Archived records are excluded. Marketing Hub tables are not yet covered. Errors name a code (`HUBSPOT_AUTH`, `HUBSPOT_SCHEMA` and others) and never include the token or record values.

## Evidence

The shared conformance suite and unit tests pass against a mock that follows the documented properties and objects responses. No live account has been used, so the connector is a preview.

## References

- [CRM API overview](https://developers.hubspot.com/docs/api/crm/understanding-the-crm)
- [Properties API](https://developers.hubspot.com/docs/api/crm/properties)
