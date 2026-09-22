import { object, text } from "./shape.mjs";
export const runtimeContract = "ingestron.snapshot/python/v1";
const field = object(
  {
    type: {
      type: "string",
      enum: ["integer", "string", "boolean", "number", "decimal", "json"],
    },
    nullable: { type: "boolean" },
    precision: { type: "integer" },
    scale: { type: "integer" },
  },
  ["type", "nullable"],
);
export const selectionSchema = {
  type: "object",
  additionalProperties: object({
    name: text,
    fields: { type: "object", additionalProperties: field },
  }),
};
export function conforms(schema, value) {
  const allowed = new Set([
    "type",
    "oneOf",
    "properties",
    "items",
    "required",
    "additionalProperties",
    "enum",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
  ]);
  if (
    !schema ||
    typeof schema !== "object" ||
    Object.keys(schema).some((k) => !allowed.has(k))
  )
    throw Error("Unsupported connector schema keyword");
  if (
    schema.oneOf &&
    schema.oneOf.filter((s) => conforms(s, value)).length !== 1
  )
    return false;
  if (
    schema.enum &&
    !schema.enum.some((v) => JSON.stringify(v) === JSON.stringify(value))
  )
    return false;
  const isObject =
    value !== null && typeof value === "object" && !Array.isArray(value);
  const types = {
    object: isObject,
    array: Array.isArray(value),
    integer: Number.isInteger(value),
    number: typeof value === "number" && Number.isFinite(value),
    string: typeof value === "string",
    boolean: typeof value === "boolean",
    null: value === null,
  };
  if (schema.type && !types[schema.type]) return false;
  if (
    typeof value === "number" &&
    ((schema.minimum !== undefined && value < schema.minimum) ||
      (schema.maximum !== undefined && value > schema.maximum))
  )
    return false;
  if (
    typeof value === "string" &&
    (Array.from(value).length < (schema.minLength ?? 0) ||
      Array.from(value).length > (schema.maxLength ?? Infinity))
  )
    return false;
  if (
    Array.isArray(value) &&
    (value.length < (schema.minItems ?? 0) ||
      value.length > (schema.maxItems ?? Infinity) ||
      (schema.items && !value.every((v) => conforms(schema.items, v))))
  )
    return false;
  if (isObject) {
    if (!(schema.required ?? []).every((k) => Object.hasOwn(value, k)))
      return false;
    for (const [key, child] of Object.entries(value)) {
      if (schema.properties && Object.hasOwn(schema.properties, key)) {
        if (!conforms(schema.properties[key], child)) return false;
      } else if (schema.additionalProperties === false) return false;
      else if (
        typeof schema.additionalProperties === "object" &&
        !conforms(schema.additionalProperties, child)
      )
        return false;
    }
  }
  return true;
}
