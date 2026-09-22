import { object, text } from "./shape.mjs";
export const settings = {
  "singer:github@1.29.2": object(
    {
      authentication: { type: "string", enum: ["anonymous", "token"] },
      auth_token: object({ $secret: object({ env: text }) }),
      repositories: {
        type: "array",
        items: { type: "string", minLength: 3 },
        minItems: 1,
        maxItems: 10,
      },
    },
    ["repositories"],
  ),
};
