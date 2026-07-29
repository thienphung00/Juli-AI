import { describe, expect, it } from "vitest";

import { analyticsDeltaClass } from "../visual-polish";

describe("analytics visual polish helpers", () => {
  it("maps chart trends to delta utility classes", () => {
    expect(analyticsDeltaClass("positive")).toBe(
      "analytics-delta analytics-delta--positive",
    );
    expect(analyticsDeltaClass("negative")).toBe(
      "analytics-delta analytics-delta--negative",
    );
    expect(analyticsDeltaClass("neutral")).toBe(
      "analytics-delta analytics-delta--neutral",
    );
    expect(analyticsDeltaClass("warning")).toBe(
      "analytics-delta analytics-delta--warning",
    );
  });
});
