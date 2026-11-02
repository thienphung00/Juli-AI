import { describe, expect, it } from "vitest";

import { detailText } from "../../../lib/ops/api";

/** Ops routes refuse with `detail: {code, message}`; the UI must never show "[object Object]". */
describe("detailText", () => {
  it("prefers the message, then the code, then the JSON", () => {
    expect(detailText({ code: "consent_required", message: "consent first" })).toBe("consent first");
    expect(detailText({ code: "not_a_shopee_shop" })).toBe("not_a_shopee_shop");
    expect(detailText({ other: 1 })).toBe('{"other":1}');
  });

  it("keeps a plain string detail", () => {
    expect(detailText("Not Found")).toBe("Not Found");
  });
});
