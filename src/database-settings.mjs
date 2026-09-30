import { object, text } from "./shape.mjs";

// PostgreSQL, MySQL and Oracle share one connection shape; Oracle names a
// service instead of a database. Passwords are always secret references.
const identifier = { type: "string", minLength: 1, maxLength: 128 };
const secret = object({ $secret: object({ env: text }) });
const connection = (databaseKey) =>
  object(
    {
      host: { type: "string", minLength: 1, maxLength: 253 },
      port: { type: "integer", minimum: 1, maximum: 65535 },
      [databaseKey]: identifier,
      user: identifier,
      password: secret,
      tls: { type: "string", enum: ["require", "disable"] },
    },
    ["host", databaseKey, "user", "password"],
  );
export const databaseSettings = (dialect) =>
  object({
    connection: connection(dialect === "oracle" ? "service" : "database"),
  });
export const databaseTableSource = object({
  schema: identifier,
  table: identifier,
});
