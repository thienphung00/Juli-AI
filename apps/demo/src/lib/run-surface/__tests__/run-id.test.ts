import { describe, expect, it } from "vitest";

import { looksLikeRunId } from "../run-id";

describe("looksLikeRunId", () => {
  it("recognizes a real backend run id (UUID)", () => {
    expect(looksLikeRunId("6fed3803-a77e-4d55-9ea3-ac72d25e77e2")).toBe(true);
  });

  it("rejects a legacy mock execution id", () => {
    expect(looksLikeRunId("exec-create_hero_product_1-42")).toBe(false);
  });

  it("rejects an empty string", () => {
    expect(looksLikeRunId("")).toBe(false);
  });

  it("rejects a near-miss (wrong segment lengths)", () => {
    expect(looksLikeRunId("6fed3803-a77e-4d55-9ea3-ac72d25e77")).toBe(false);
  });
});
