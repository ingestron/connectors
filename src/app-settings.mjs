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
export const graphTableSource = object({
  path: { type: "string", minLength: 1, maxLength: 1024 },
  format: fileFormat,
});
