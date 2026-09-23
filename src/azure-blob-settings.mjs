import { object, text } from "./shape.mjs";
import { fileFormat, legacyFileTypes } from "./files-settings.mjs";
export const azureBlobSettings = object(
  {
    account: { type: "string", minLength: 3, maxLength: 24 },
    container: { type: "string", minLength: 3, maxLength: 63 },
    blob: { type: "string", minLength: 1, maxLength: 1024 },
    sas_token: object({ $secret: object({ env: text }) }),
    format: fileFormat,
    types: legacyFileTypes,
  },
  ["account", "container", "blob", "sas_token", "format"],
);
