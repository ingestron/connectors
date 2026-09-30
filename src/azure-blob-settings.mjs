import { object, text } from "./shape.mjs";
import { fileFormat } from "./files-settings.mjs";

// Azure Blob 2.0: the connection names the account, container and SAS; each
// flow table chooses its blob path and format, and its contract the types.
export const azureBlobSettings = object({
  account: { type: "string", minLength: 3, maxLength: 24 },
  container: { type: "string", minLength: 3, maxLength: 63 },
  sas_token: object({ $secret: object({ env: text }) }),
});
export const azureBlobTableSource = object({
  path: { type: "string", minLength: 1, maxLength: 1024 },
  format: fileFormat,
});
