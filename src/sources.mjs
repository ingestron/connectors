// Source kind, capabilities and reference record per connector (PB-064).
// Maturity follows recorded evidence only; update `verified` when rechecked.
const docs = (name) =>
  `https://github.com/ingestron/connectors/blob/main/docs/${name}.md`;
const verified = "2026-09-30";
const checked = "2026-10-01";
const snapshot = ["snapshot", "discovery"];

const database = (kind, label, docsName, driver, licence, access) => ({
  kind,
  capabilities: snapshot,
  reference: {
    docs: docs(docsName),
    vendorStatus: "not-applicable",
    licence: `Apache-2.0; upstream ${driver} ${licence}`,
    cost: { model: "none", note: "Database compute and egress charges apply" },
    access: { model: "free", ...access },
    auth: ["password"],
    network: ["public", "private-network", "on-premises"],
    maturity: "verified",
    verified,
    note: `${label} tables through a pure-Python driver; conformance suite passed against a local ${label} container`,
  },
});

const graphFiles = (kind, label, auth) => ({
  kind,
  capabilities: snapshot,
  reference: {
    docs: docs(kind),
    vendorStatus: "not-applicable",
    licence:
      "Apache-2.0; upstream pyarrow Apache-2.0; HTTPS through the Python standard library",
    cost: {
      model: "none",
      note: "Microsoft Graph file reads carry no separate charge; Microsoft 365 licensing applies",
    },
    access: {
      model: "subscription",
      url: "https://learn.microsoft.com/graph/api/resources/onedrive",
      note: `A Microsoft 365 tenant and an Entra app with ${auth} application permission`,
    },
    auth: ["client-credentials"],
    network: ["public"],
    maturity: "preview",
    verified,
    note: `${label} files and folders through Microsoft Graph v1.0; conformance and unit tests against a Graph mock only; no live tenant`,
  },
});

const api = (
  kind,
  label,
  url,
  accessModel,
  accessUrl,
  accessNote,
  auth,
  what,
) => ({
  kind,
  capabilities: snapshot,
  reference: {
    docs: docs(kind),
    vendorStatus: "not-applicable",
    licence: "Apache-2.0; HTTPS through the Python standard library",
    cost: {
      model: "none",
      note: `${label} API use has no separate charge; plan limits apply`,
    },
    access: { model: accessModel, url: accessUrl, note: accessNote },
    auth,
    network: ["public"],
    maturity: "preview",
    verified: checked,
    note: `${what}; conformance suite against a mock of the documented API only; no live account`,
  },
});

export const sources = {
  files: {
    kind: "local-files",
    capabilities: snapshot,
    reference: {
      docs: docs("files"),
      vendorStatus: "not-applicable",
      licence: "Apache-2.0; upstream pyarrow Apache-2.0",
      cost: { model: "none" },
      access: { model: "none", note: "Files on the machine running the flow" },
      auth: [],
      network: ["local"],
      maturity: "verified",
      verified,
      note: "Installed runs read real CSV, TSV, JSON, JSONL and Parquet files",
    },
  },
  "azure-blob": {
    kind: "azure-blob",
    capabilities: snapshot,
    reference: {
      docs: docs("azure-blob"),
      vendorStatus: "not-applicable",
      licence: "Apache-2.0; upstream pyarrow Apache-2.0",
      cost: {
        model: "none",
        pricing: "https://azure.microsoft.com/pricing/details/storage/blobs/",
        note: "Azure Storage read and egress charges apply",
      },
      access: {
        model: "subscription",
        url: "https://learn.microsoft.com/azure/storage/blobs/",
        note: "An existing storage account and a read-only SAS token",
      },
      auth: ["sas"],
      network: ["public"],
      maturity: "preview",
      verified,
      note: "Conformance suite and installed runs against a loopback server only; no live storage account",
    },
  },
  "sql-server": {
    kind: "sql-server",
    capabilities: snapshot,
    reference: {
      docs: docs("sql-server"),
      vendorStatus: "not-applicable",
      licence:
        "Apache-2.0; upstream mssql-python MIT, bundled ODBC binary under Microsoft terms",
      cost: {
        model: "none",
        note: "Database compute and egress charges apply",
      },
      access: {
        model: "free",
        url: "https://www.microsoft.com/sql-server/sql-server-downloads",
        note: "SQL Server Developer edition or an existing SQL Server or Azure SQL database",
      },
      auth: [
        "sql-password",
        "entra-default",
        "entra-managed-identity",
        "entra-service-principal",
      ],
      network: ["public", "private-network", "on-premises"],
      maturity: "verified",
      verified,
      note: "Conformance suite passed against SQL Server 2022 Developer in a local container (certificate trust relaxed for the test only); an earlier release read Northwind live",
    },
  },
  postgresql: database(
    "postgresql",
    "PostgreSQL",
    "postgresql",
    "pg8000",
    "BSD-3-Clause",
    {
      url: "https://www.postgresql.org/download/",
      note: "PostgreSQL is free; any existing server",
    },
  ),
  mysql: database("mysql", "MySQL and MariaDB", "mysql", "PyMySQL", "MIT", {
    url: "https://dev.mysql.com/downloads/mysql/",
    note: "MySQL Community Server is free; any existing server",
  }),
  oracle: database(
    "oracle",
    "Oracle",
    "oracle",
    "python-oracledb",
    "UPL-1.0 OR Apache-2.0",
    {
      url: "https://www.oracle.com/database/free/",
      note: "Oracle Database Free or an existing database",
    },
  ),
  stripe: {
    kind: "stripe",
    capabilities: snapshot,
    reference: {
      docs: docs("stripe"),
      vendorStatus: "not-applicable",
      licence:
        "Apache-2.0; upstream pyarrow Apache-2.0; HTTPS through the Python standard library",
      cost: { model: "none", note: "The Stripe API has no per-call charge" },
      access: {
        model: "free",
        url: "https://docs.stripe.com/keys",
        note: "Test-mode keys in a free Stripe account; use a restricted read-only key",
      },
      auth: ["api-key"],
      network: ["public"],
      maturity: "preview",
      verified,
      note: "Documented list API with cursor pagination; conformance suite against a mock of that API only; no live Stripe account",
    },
  },
  s3: {
    kind: "s3",
    capabilities: snapshot,
    reference: {
      docs: docs("s3"),
      vendorStatus: "not-applicable",
      licence:
        "Apache-2.0; upstream pyarrow Apache-2.0; SigV4 signing with the Python standard library",
      cost: {
        model: "none",
        pricing: "https://aws.amazon.com/s3/pricing/",
        note: "S3 request and data transfer charges apply",
      },
      access: {
        model: "subscription",
        url: "https://docs.aws.amazon.com/AmazonS3/latest/userguide/",
        note: "An AWS account and an access key with s3:ListBucket and s3:GetObject; S3-compatible stores through endpoint",
      },
      auth: ["access-key"],
      network: ["public"],
      maturity: "verified",
      verified: checked,
      note: "Conformance suite against an S3-compatible server (SeaweedFS) in a local container that verifies SigV4 signatures; not yet against AWS itself",
    },
  },
  gcs: {
    kind: "gcs",
    capabilities: snapshot,
    reference: {
      docs: docs("gcs"),
      vendorStatus: "not-applicable",
      licence:
        "Apache-2.0; upstream pyarrow Apache-2.0; SigV4 signing with the Python standard library",
      cost: {
        model: "none",
        pricing: "https://cloud.google.com/storage/pricing",
        note: "Cloud Storage operation and egress charges apply",
      },
      access: {
        model: "subscription",
        url: "https://cloud.google.com/storage/docs/authentication/hmackeys",
        note: "A Google Cloud project and an HMAC key for a service account with read access",
      },
      auth: ["hmac-key"],
      network: ["public"],
      maturity: "preview",
      verified: checked,
      note: "XML API with HMAC keys; shares the S3 signing path verified against an S3-compatible server; conformance against a mock only",
    },
  },
  sftp: {
    kind: "sftp",
    capabilities: snapshot,
    reference: {
      docs: docs("sftp"),
      vendorStatus: "not-applicable",
      licence:
        "Apache-2.0; upstream pyarrow Apache-2.0; uses the machine's OpenSSH client (not bundled)",
      cost: { model: "none" },
      access: {
        model: "none",
        note: "An SFTP server, a user with a key, and its host key",
      },
      auth: ["ssh-key"],
      network: ["public", "private-network", "on-premises"],
      maturity: "verified",
      verified: checked,
      note: "System OpenSSH sftp with a pinned host key; conformance suite against an SFTP server in a local container",
    },
  },
  salesforce: api(
    "salesforce",
    "Salesforce",
    "https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/",
    "free",
    "https://developer.salesforce.com/signup",
    "A Salesforce Developer Edition org is free; a connected app with client credentials",
    ["oauth2-client-credentials"],
    "REST API describe and SOQL query; API limits apply",
  ),
  hubspot: api(
    "hubspot",
    "HubSpot",
    "https://developers.hubspot.com/docs/api/crm/understanding-the-crm",
    "free-tier",
    "https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/overview",
    "A HubSpot account with a private app token and CRM read scopes",
    ["private-app-token"],
    "CRM v3 objects and properties; daily API limits apply",
  ),
  jira: api(
    "jira",
    "Jira Cloud",
    "https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/",
    "free-tier",
    "https://www.atlassian.com/software/jira/free",
    "A Jira Cloud site (the free plan has the REST API) and an API token",
    ["api-token"],
    "REST API v3 fields and enhanced JQL search; rate limits apply",
  ),
  sharepoint: graphFiles(
    "sharepoint",
    "SharePoint document library",
    "Sites.Selected or Sites.Read.All",
  ),
  onedrive: graphFiles("onedrive", "OneDrive for Business", "Files.Read.All"),
  github: {
    kind: "github",
    capabilities: snapshot,
    reference: {
      docs: docs("github"),
      vendorStatus: "not-applicable",
      licence: "Apache-2.0; upstream MeltanoLabs tap-github Apache-2.0",
      cost: { model: "none", note: "GitHub API rate limits apply" },
      access: {
        model: "free",
        url: "https://docs.github.com/rest",
        note: "Public repositories anonymously; a token for private repositories",
      },
      auth: ["anonymous", "token"],
      network: ["public"],
      maturity: "verified",
      verified,
      note: "A bounded anonymous live run against a public repository passed",
    },
  },
};
