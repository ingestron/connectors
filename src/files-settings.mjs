import { object, text } from "./shape.mjs";

export const fileFormat = {
  type: "string",
  enum: ["csv", "tsv", "json", "jsonl", "parquet"],
};
// Local files need no shared endpoint or credential. The connection carries
// source/tenant identity; each table chooses its own physical file and format.
export const filesSettings = object({});
export const filesTableSource = object({
  path: text,
  format: fileFormat,
});
