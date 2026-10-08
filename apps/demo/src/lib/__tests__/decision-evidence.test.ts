import { GOLDEN_DEMO_DECISION_EXECUTABLE, type DemoDecisionItem } from "@juli/contracts";
import { describe, expect, it } from "vitest";

import { mapDecisionEvidence } from "../decision-evidence";
import realItem from "./fixtures/adr106-decision-item.json";

/**
 * `fixtures/adr106-decision-item.json` is a verbatim item of a real
 * `GET /v1/demo/decisions` response, captured from the backend test
 * `tests/unit/test_optimize_product_decision_cards.py::
 * test_decisions_endpoint_returns_diagnosis_and_evidence` (P7-B models in
 * `api/routes/demo_decisions.py`). Re-capture it if those models change.
 */
const item = realItem as unknown as DemoDecisionItem;

describe("mapDecisionEvidence — P7-B Optimize Product fields", () => {
  it("returns null for a card without a diagnosis (old rendering)", () => {
    expect(mapDecisionEvidence(GOLDEN_DEMO_DECISION_EXECUTABLE)).toBeNull();
    expect(mapDecisionEvidence(null)).toBeNull();
    expect(
      mapDecisionEvidence({
        ...item,
        recommendation: { ...item.recommendation, diagnosis: null },
      }),
    ).toBeNull();
  });

  it("maps the real backend item: stage, lever action, trigger, recoverable GMV", () => {
    const evidence = mapDecisionEvidence(item);
    expect(evidence).toMatchObject({
      stage: "Hiển thị → Nhấp (thẻ sản phẩm)",
      lever: "Viết lại tiêu đề",
      trigger: "CTR thẻ sản phẩm ước tính thấp hơn 60 % so với trung bình shop trong 14 ngày qua",
      recoverableGmvPerDay: 1200000,
      windowDays: 30,
      asOf: "2026-10-06",
      notes: [],
    });
  });

  it("keeps the backend's metrics, labels and order; ratios stay fractions", () => {
    const evidence = mapDecisionEvidence(item);
    expect(evidence?.metrics.map((m) => [m.key, m.label, m.unit])).toEqual([
      ["impressions", "Lượt hiển thị sản phẩm", "count"],
      ["ctr", "CTR", "ratio"],
      ["add_to_cart_rate", "Tỷ lệ thêm vào giỏ hàng", "ratio"],
      ["ctor", "CTOR", "ratio"],
      ["aov", "AOV", "vnd"],
      ["gmv", "GMV trung bình mỗi ngày", "vnd"],
      ["sku_orders", "Đơn hàng SKU mỗi ngày", "count"],
    ]);
    const ctr = evidence?.metrics.find((m) => m.key === "ctr");
    expect(ctr).toMatchObject({ current: 0.02, previous: 0.02, change: 0, confidence: "Tham khảo" });
    const cart = evidence?.metrics.find((m) => m.key === "add_to_cart_rate");
    expect(cart).toMatchObject({ previous: null, change: null, confidence: null });
    expect(cart?.note).toMatch(/5 ngày/);
  });

  it("falls back to expected_impact for the recoverable GMV and to the lever label", () => {
    const recommendation = item.recommendation;
    const diagnosis = recommendation.diagnosis!;
    const evidence = mapDecisionEvidence({
      ...item,
      recommendation: {
        ...recommendation,
        evidence: null,
        diagnosis: {
          ...diagnosis,
          recoverable_gmv_per_day: null,
          lever: { ...diagnosis.lever, action: "" },
        },
      },
    });
    expect(evidence?.recoverableGmvPerDay).toBe(1200000);
    expect(evidence?.lever).toBe("tiêu đề");
    expect(evidence?.metrics).toEqual([]);
  });

  it("drops an unknown confidence value instead of showing it", () => {
    const recommendation = item.recommendation;
    const evidence = mapDecisionEvidence({
      ...item,
      recommendation: {
        ...recommendation,
        evidence: {
          ...recommendation.evidence!,
          metrics: [{ key: "ctr", label: "CTR", unit: "ratio", current: 0.1, confidence: "high" }],
        },
      },
    });
    expect(evidence?.metrics[0]?.confidence).toBeNull();
  });
});
