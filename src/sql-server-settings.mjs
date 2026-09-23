import { object, text } from "./shape.mjs";

const identifier = { type: "string", minLength: 1, maxLength: 128 };
const secret = object({ $secret: object({ env: text }) });
const sqlPassword = object({
  method: { type: "string", enum: ["sql-password"] },
  username: identifier,
  password: secret,
});
const entraDefault = object({
  method: { type: "string", enum: ["entra-default"] },
});
const entraManagedIdentity = object(
  {
    method: { type: "string", enum: ["entra-managed-identity"] },
    client_id: identifier,
  },
  ["method"],
);
const entraServicePrincipal = object({
  method: { type: "string", enum: ["entra-service-principal"] },
  client_id: identifier,
  client_secret: secret,
});

// Object selection is independent of the local connection. ADF and Databricks
// can bind this source intent to their own native connection objects later.
export const sqlServerSettings = object({
  object: object(
    {
      schema: identifier,
      table: identifier,
      columns: { type: "array", items: identifier, minItems: 1, maxItems: 500 },
    },
    ["schema", "table"],
  ),
  connection: object(
    {
      server: { type: "string", minLength: 1, maxLength: 253 },
      database: identifier,
      port: { type: "integer", minimum: 1, maximum: 65535 },
      authentication: {
        oneOf: [
          sqlPassword,
          entraDefault,
          entraManagedIdentity,
          entraServicePrincipal,
        ],
      },
    },
    ["server", "database", "authentication"],
  ),
});
