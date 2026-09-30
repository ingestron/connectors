# Jira Cloud issues and projects

Reads Jira Cloud issues, projects, issue types, statuses and users into reviewed local snapshots through the REST API v3. One connection names the site and an account's API token; each table names one of those objects. It only reads.

| Package  | `jira@0.1.0`                                                    |
| -------- | --------------------------------------------------------------- |
| Kind     | `jira`                                                          |
| Maturity | preview: conformance suite against a mock of the documented API |
| Licence  | Adapter Apache-2.0; HTTPS through the Python standard library   |
| Cost     | No Ingestron charge; Jira rate limits apply                     |

## Install

```sh
ingestron connector install jira@0.1.0
```

## Connection

Create an [API token](https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/) for an account with browse access to the projects. The free Jira plan includes the REST API. Keep the token in an environment variable referenced with `$secret`.

```yaml
connections:
  source:
    package: jira
    sourceId: source
    tenantId: training
    settings:
      site: https://acme.atlassian.net
      email: reader@example.com
      api_token:
        $secret:
          env: JIRA_API_TOKEN
flows:
  - apiVersion: ingestron.flow/v1
    kind: ingestion
    id: source_local
    provider: local
    ingestion:
      connection: source
      execution: { mode: local }
    tables:
      issues:
        source: { object: issues, jql: "project = OPS ORDER BY created ASC" }
        contract: { $resolve: ./contracts/issues.odcs.yaml }
```

## Tables

| `source` key | Meaning                                                                                |
| ------------ | -------------------------------------------------------------------------------------- |
| `object`     | `issues`, `projects`, `issue_types`, `status` or `users`                               |
| `jql`        | Issues only: a bounded JQL query (default `project IS NOT EMPTY ORDER BY created ASC`) |

## Types

Issue columns are `id`, `key` and field IDs from `/rest/api/3/field` (such as `summary`, `status` or `customfield_10016`). Object values become their name, value or display name; lists become JSON text; number fields can be contracted as integer or decimal. Other tables have fixed fields listed in the runtime.

## Behaviour and limits

Issues use the enhanced search (`POST /rest/api/3/search/jql`) with `nextPageToken` paging; Jira requires a bounded query. A repeated page token or issue fails the run instead of looping (a known issue with this endpoint). Deleted issues are not tracked. Errors name a code (`JIRA_AUTH`, `JIRA_SCHEMA`, `JIRA_RESPONSE` and others) and never include the token or values.

## Evidence

The shared conformance suite and unit tests pass against a mock that follows the documented field, search and paged responses. No live site has been used, so the connector is a preview. ADF has no usable native Jira route; Databricks reads Jira through Lakeflow Connect (Beta).

## References

- [REST API v3](https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/)
- [Issue search](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/)
