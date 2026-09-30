import { object, text } from "./shape.mjs";
import { fileFormat } from "./files-settings.mjs";

// Business applications and Microsoft 365 (PB-064 phase 4). Credentials are
// always secret references; each table names one object or one file/folder.
const secret = object({ $secret: object({ env: text }) });
const guid = { type: "string", minLength: 36, maxLength: 36 };

export const stripeSettings = object({ api_key: secret });
export const stripeTableSource = object({
  object: { type: "string", minLength: 1, maxLength: 64 },
});

const graph = (extra) =>
  object({ tenant_id: guid, client_id: guid, client_secret: secret, ...extra });
export const sharepointSettings = graph({
  site: { type: "string", minLength: 30, maxLength: 300 },
});
export const onedriveSettings = graph({
  user: { type: "string", minLength: 3, maxLength: 320 },
});
// Files name a format; SharePoint lists use entity: list (PB-064 phase 7).
export const graphTableSource = object(
  {
    path: { type: "string", minLength: 1, maxLength: 1024 },
    format: fileFormat,
    entity: { type: "string", enum: ["file", "list"] },
  },
  ["path"],
);
export const graphFileSource = object({
  path: { type: "string", minLength: 1, maxLength: 1024 },
  format: fileFormat,
});

// Object stores and SFTP (PB-064 phase 7).
const text64 = { type: "string", minLength: 1, maxLength: 256 };
export const s3Settings = object(
  {
    bucket: { type: "string", minLength: 3, maxLength: 63 },
    region: { type: "string", minLength: 4, maxLength: 32 },
    access_key_id: text64,
    secret_access_key: secret,
    session_token: secret,
    endpoint: { type: "string", minLength: 8, maxLength: 300 },
  },
  ["bucket", "region", "access_key_id", "secret_access_key"],
);
export const gcsSettings = object({
  bucket: { type: "string", minLength: 3, maxLength: 63 },
  access_key_id: text64,
  secret_access_key: secret,
});
export const sftpSettings = object(
  {
    host: { type: "string", minLength: 1, maxLength: 253 },
    port: { type: "integer", minimum: 1, maximum: 65535 },
    user: { type: "string", minLength: 1, maxLength: 64 },
    private_key: secret,
    host_key: { type: "string", minLength: 20, maxLength: 1024 },
  },
  ["host", "user", "private_key", "host_key"],
);
export const fileTableSource = graphFileSource;

// Business applications (PB-064 phase 7).
const objectName = { type: "string", minLength: 1, maxLength: 80 };
export const salesforceSettings = object({
  instance_url: { type: "string", minLength: 12, maxLength: 300 },
  client_id: { type: "string", minLength: 1, maxLength: 1024 },
  client_secret: secret,
});
export const hubspotSettings = object({ access_token: secret });
export const jiraSettings = object({
  site: { type: "string", minLength: 12, maxLength: 300 },
  email: { type: "string", minLength: 3, maxLength: 320 },
  api_token: secret,
});
export const objectTableSource = object({ object: objectName });
export const jiraTableSource = object(
  {
    object: objectName,
    jql: { type: "string", minLength: 1, maxLength: 2000 },
  },
  ["object"],
);
