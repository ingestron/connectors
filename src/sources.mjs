// Source kind, capabilities and reference record per connector (PB-064).
// Maturity follows recorded evidence only; update `verified` when rechecked.
const docs = (name) =>
  `https://github.com/ingestron/connectors/blob/main/docs/${name}.md`;
const verified = "2026-09-30";
const snapshot = ["snapshot", "discovery"];

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
      note: "Tested against a loopback server only; no live storage account",
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
      maturity: "preview",
      verified,
      note: "Multi-table reads tested synthetically; an earlier single-table release read Northwind live",
    },
  },
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
