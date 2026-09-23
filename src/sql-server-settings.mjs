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

// The connection is reusable across tables; each flow table selects its own
// physical object and receives its columns from the reviewed ODCS contract.
export const sqlServerTableSource = object({
  schema: identifier,
  table: identifier,
});
export const sqlServerSettings = object({
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
