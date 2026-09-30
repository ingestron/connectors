# Stripe objects

Reads Stripe objects (customers, charges, invoices and others) into reviewed
local snapshots through Stripe's list API. One connection holds the API key;
each `flows[].tables` entry names one object, and its ODCS contract chooses the
fields. The connector only reads: it never creates, updates or expands objects.

| Package  | `stripe@0.1.0`                                                                    |
| -------- | --------------------------------------------------------------------------------- |
| Kind     | `stripe`                                                                          |
| Maturity | preview: conformance suite against a mock of the documented list API              |
| Licence  | Adapter Apache-2.0; HTTPS through the Python standard library; pyarrow Apache-2.0 |
| Cost     | No Ingestron charge; the Stripe API has no per-call charge                        |

## Install

```sh
ingestron connector install stripe@0.1.0
```

## Connection

Create a [restricted key](https://docs.stripe.com/keys) with read access to the
objects you select. Test-mode keys (`rk_test_…`) read a free sandbox; live keys
read real data. Store the key in an environment variable and reference it with
`$secret`; never put it in YAML.

```yaml
connections:
  payments:
    package: stripe
    sourceId: payments
    tenantId: training
    settings:
      api_key:
        $secret:
          env: STRIPE_API_KEY
flows:
  - apiVersion: ingestron.flow/v1
    kind: ingestion
    id: payments_local
    provider: local
    ingestion:
      connection: payments
      execution: { mode: local }
    tables:
      customers:
        source: { object: customers }
        contract: { $resolve: ./contracts/customers.odcs.yaml }
```

## Tables

| `source` key | Meaning                                    |
| ------------ | ------------------------------------------ |
| `object`     | One of the objects below, by its list path |

Every object also offers `id`, `object`, `created` (Unix seconds) and
`livemode`. Selectable top-level fields:

| Object                 | Fields                                                                                                                                                                                                                       |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `balance_transactions` | `amount`, `available_on`, `currency`, `description`, `fee`, `net`, `status`, `type`, `reporting_category`, `source`                                                                                                          |
| `charges`              | `amount`, `amount_captured`, `amount_refunded`, `currency`, `customer`, `description`, `paid`, `refunded`, `captured`, `status`, `payment_intent`, `receipt_email`, `failure_code`, `failure_message`, `balance_transaction` |
| `customers`            | `email`, `name`, `description`, `phone`, `currency`, `balance`, `delinquent`                                                                                                                                                 |
| `invoices`             | `customer`, `status`, `currency`, `amount_due`, `amount_paid`, `amount_remaining`, `total`, `subtotal`, `number`, `due_date`, `collection_method`, `customer_email`, `period_start`, `period_end`                            |
| `payment_intents`      | `amount`, `amount_received`, `currency`, `customer`, `description`, `status`, `capture_method`, `canceled_at`, `cancellation_reason`, `latest_charge`                                                                        |
| `prices`               | `active`, `currency`, `unit_amount`, `product`, `type`, `nickname`, `billing_scheme`, `lookup_key`                                                                                                                           |
| `products`             | `name`, `description`, `active`, `updated`, `url`, `default_price`                                                                                                                                                           |
| `refunds`              | `amount`, `charge`, `currency`, `payment_intent`, `reason`, `status`                                                                                                                                                         |
| `subscriptions`        | `customer`, `status`, `currency`, `cancel_at_period_end`, `canceled_at`, `start_date`, `ended_at`, `collection_method`, `description`                                                                                        |

## Types

Amounts and timestamps are integers (amounts in the currency's minor unit),
flags are booleans and everything else is a string. Contract types must match:
`BIGINT` for integers, `BOOLEAN` for flags and `STRING` for text. Nested objects,
lists and `metadata` are not selectable. Expandable references such as
`customer` are read as IDs.

## Behaviour and limits

Discovery reads the first page to check access and field shapes. A run reads
every page with `limit=100` and the `starting_after` cursor, newest first, and
fails with `STRIPE_SCHEMA` if any record lacks a selected field or has a
different type. Every selected table is read before any record is committed.
Reads are full snapshots of up to one million records per object; there is no
incremental cursor. The account's default API version applies. Errors name a
safe code (`STRIPE_AUTH`, `STRIPE_FORBIDDEN`, `STRIPE_RATE_LIMIT`,
`STRIPE_UNAVAILABLE`, `STRIPE_RESPONSE`, `STRIPE_NETWORK`) and never include
the key or record values. Rate limits fail the run rather than retrying.

## Evidence

The shared conformance suite and unit tests pass against an in-memory mock that
follows Stripe's documented list behaviour (pagination, authentication and
error bodies). No live Stripe account has been used, so the connector is a
preview. Neither ADF nor Databricks offers a native Stripe connector.

## References

- [List API and pagination](https://docs.stripe.com/api/pagination)
- [API keys](https://docs.stripe.com/keys) and [restricted keys](https://docs.stripe.com/keys#limit-access)
- [Stripe OpenAPI description](https://github.com/stripe/openapi)
