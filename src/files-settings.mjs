import { object, text } from "./shape.mjs";
export const filesSettings = object(
  {
    path: text,
    format: {
      type: "string",
      enum: ["csv", "tsv", "json", "jsonl", "parquet"],
    },
    types: {
      type: "object",
      additionalProperties: {
        type: "string",
        enum: ["string", "integer", "decimal", "number", "boolean"],
      },
    },
  },
  ["path", "format"],
);
