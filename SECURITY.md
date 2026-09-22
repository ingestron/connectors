# Security

Report vulnerabilities through [GitHub private reporting](https://github.com/ingestron/connectors/security/advisories/new).
Never include tokens, customer records or private source output in public issues.

Runtime preparation downloads and installs locked Python dependencies, including
upstream build code where required. Execution runs trusted code in the user's
context, not a sandbox. Review packages and use least-privilege source credentials.

Secrets are references in authored files, resolved only for execution. Child tap
configuration is temporary with restrictive permissions; upstream logs are withheld.
Parquet, contracts and receipts can contain sensitive records/metadata and require
appropriate filesystem protection. A completed replay verifies existing bytes and
does not contact the source. Do not edit runtime locks or committed output.
