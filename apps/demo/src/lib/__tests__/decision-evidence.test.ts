import { GOLDEN_DEMO_DECISION_EXECUTABLE } from "@juli/contracts";
import { describe, expect, it } from "vitest";

import { mapDecisionEvidence } from "../decision-evidence";

const base = GOLDEN_DEMO_DECISION_EXECUTABLE;

describe("mapDecisionEvidence — tolerant reader of the P7-B additive fields", () => {
  it("returns null for an item without any of the new fields (today's envelope)", () => {
    expect(mapDecisionEvidence(base)).toBeNull();
    expect(mapDecisionEvidence(null)).toBeNull();
  });

  it("reads the assumed shape: diagnosis labels + metrics array, in TikTok's order", () => {
    const evidence = mapDecisionEvidence({
      ...base,
      diagnosis: { stage: "ctor", stage_label: "CTOR — sau giỏ", lever: "voucher" },
      funnel_evidence: {
        as_of: "2026-10-06",
        metrics: [
          { key: "aov", prior: 180000, last: 175000, confidence: "Tham khảo" },
          { key: "impressions", prior: 2500, last: 3200, confidence: "Rõ" },
          { key: "ctor", prior: 0.06, last: 0.038, confidence: "clear" },
          { key: "mystery", prior: 1, last: 2 },
        ],
      },
    });
    expect(evidence?.stage).toBe("CTOR — sau giỏ");
    expect(evidence?.lever).toBe("Voucher");
    expect(evidence?.asOf).toBe("2026-10-06");
    expect(evidence?.metrics.map((m) => m.key)).toEqual(["impressions", "ctor", "aov"]);
    expect(evidence?.metrics[1]).toMatchObject({ label: "CTOR", confidence: "Rõ" });
  });

  it("accepts flat fields, an object of metrics and alternative value names", () => {
    const evidence = mapDecisionEvidence({
      ...base,
      stage: "before_cart",
      evidence: {
        ctr: { previous: 0.04, current: 0.05, confidence: "insufficient" },
        add_to_cart_rate: { prior_30d: "0.12", last_30d: "0.10" },
      },
    });
    expect(evidence?.stage).toBe("Trước giỏ");
    expect(evidence?.lever).toBeNull();
    expect(evidence?.metrics).toEqual([
      { key: "ctr", label: "CTR (Tỷ lệ nhấp)", prior: 0.04, last: 0.05, confidence: "Chưa đủ dữ liệu" },
      { key: "add_to_cart_rate", label: "Tỷ lệ thêm vào giỏ hàng", prior: 0.12, last: 0.1, confidence: null },
    ]);
  });

  it("never surfaces an unknown snake_case code to the seller", () => {
    expect(mapDecisionEvidence({ ...base, diagnosis: { stage: "weird_internal_code" } })).toBeNull();
  });
});
