import { describe, expect, it } from "vitest";

import {
  PLAN_CAVEAT_CLASSES,
  PLAN_CAVEAT_PLACEMENT,
  REASSURANCE_CAVEAT_WORKFLOW_KEYS,
  WORKFLOW_PLAN_CAVEATS,
  getHiddenCaveats,
  getPlanCaveats,
  getReasoningCaveats,
  getReassuranceCaveats,
  hasReassuranceCaveat,
  isRenderedCaveatClass,
  selectPlanCaveats,
  type PlanCaveatClass,
} from "../plan-caveats";
import { recommendationFixtures } from "../recommendations";
import {
  REVIEW_UI_BANNED_PATTERNS,
  sanitizeSellerReviewText,
} from "../review-seller-copy";

/**
 * Typed caveat classes (ADR-055 item 10; PRD #758 stories 41–44, 47).
 *
 * `knownLimits` was one concatenated blob of four different kinds of
 * statement, so the card could not render one differently from another. The
 * classification below is the contract: a misfiled string fails here rather
 * than shipping.
 */
const EXPECTED_CLASSIFICATION: Record<string, PlanCaveatClass[]> = {
  create_hero_product_1: ["threshold-undefined", "fulfilment-unsupported"],
  optimize_product_2: ["threshold-undefined"],
  // gitleaks:allow — documented mock workflow key
  replenish_inventory_3: ["threshold-undefined", "fulfilment-unsupported"],
  clear_excess_4: ["threshold-undefined", "threshold-undefined"],
  process_order_5: ["threshold-undefined", "fulfilment-unsupported"],
  create_activity_7a: [
    "threshold-undefined",
    "feature-unavailable",
    "fulfilment-unsupported",
  ],
  update_activity_7c: [
    "threshold-undefined",
    "feature-unavailable",
    "feature-unavailable",
    "fulfilment-unsupported",
  ],
  delete_activity_7b: [
    "threshold-undefined",
    "feature-unavailable",
    "fulfilment-unsupported",
  ],
  prevent_cancellation_8a: ["threshold-undefined", "reassurance"],
  prevent_return_8b: [
    "threshold-undefined",
    "reassurance",
    "fulfilment-unsupported",
  ],
  prevent_refund_8c: ["threshold-undefined", "reassurance"],
};

/** Workflows carrying at least one caveat of the given class. */
function workflowsCarrying(caveatClass: PlanCaveatClass): string[] {
  return Object.keys(EXPECTED_CLASSIFICATION).filter((workflowKey) =>
    getPlanCaveats(workflowKey).some(
      (caveat) => caveat.caveatClass === caveatClass,
    ),
  );
}

describe("typed caveat classes", () => {
  it("covers all eleven workflows in the shared fixture table", () => {
    expect(recommendationFixtures).toHaveLength(11);

    for (const fixture of recommendationFixtures) {
      expect(WORKFLOW_PLAN_CAVEATS[fixture.workflowKey]).toBeDefined();
      expect(getPlanCaveats(fixture.workflowKey).length).toBeGreaterThan(0);
    }

    expect(Object.keys(WORKFLOW_PLAN_CAVEATS)).toHaveLength(11);
  });

  it("classifies every caveat on every workflow — a misfiled string fails here", () => {
    for (const [workflowKey, classes] of Object.entries(
      EXPECTED_CLASSIFICATION,
    )) {
      expect(
        getPlanCaveats(workflowKey).map((caveat) => caveat.caveatClass),
      ).toEqual(classes);
    }
  });

  it("matches the corpus counts the decomposition was measured against", () => {
    // ADR-055 item 10: A 11/11, B 7/11, C 3/11, D 3/11.
    expect(workflowsCarrying("threshold-undefined")).toHaveLength(11);
    expect(workflowsCarrying("fulfilment-unsupported")).toHaveLength(7);
    expect(workflowsCarrying("feature-unavailable")).toHaveLength(3);
    expect(workflowsCarrying("reassurance")).toHaveLength(3);
  });

  it("names the promotions trio as the only workflows with a real functional gap", () => {
    expect(workflowsCarrying("feature-unavailable")).toEqual([
      "create_activity_7a",
      "update_activity_7c",
      "delete_activity_7b",
    ]);
  });

  it("gives every caveat non-empty pre-authored text", () => {
    for (const workflowKey of Object.keys(WORKFLOW_PLAN_CAVEATS)) {
      for (const caveat of getPlanCaveats(workflowKey)) {
        expect(caveat.text.trim().length).toBeGreaterThan(0);
        expect(PLAN_CAVEAT_CLASSES).toContain(caveat.caveatClass);
      }
    }
  });

  it("returns an empty list for a workflow with no caveat entry", () => {
    expect(getPlanCaveats("not_a_workflow")).toEqual([]);
    expect(hasReassuranceCaveat("not_a_workflow")).toBe(false);
  });
});

describe("the A-vs-D distinction", () => {
  /**
   * "không tự **suy diễn**" (Juli will not invent the number) is class A — a
   * threshold that was never defined. It is NOT a promise that Juli will not
   * act unaided. Filing it as reassurance would hide a real limitation and
   * wrongly block repeat consent downstream (#775).
   */
  const WONT_INFER_STRINGS = [
    { workflowKey: "create_hero_product_1", fragment: "không tự suy diễn" },
    { workflowKey: "clear_excess_4", fragment: "không tự suy diễn" },
  ];

  it.each(WONT_INFER_STRINGS)(
    'files "$fragment" on $workflowKey as a threshold, never as reassurance',
    ({ workflowKey, fragment }) => {
      const matching = getPlanCaveats(workflowKey).filter((caveat) =>
        caveat.text.includes(fragment),
      );

      expect(matching.length).toBeGreaterThan(0);
      for (const caveat of matching) {
        expect(caveat.caveatClass).toBe("threshold-undefined");
      }
    },
  );

  it("keeps every won't-infer string out of the reassurance class corpus-wide", () => {
    for (const workflowKey of Object.keys(WORKFLOW_PLAN_CAVEATS)) {
      for (const caveat of getReassuranceCaveats(workflowKey)) {
        expect(caveat.text).not.toContain("suy diễn");
      }
    }
  });

  it("files the no-act-without-you promises as reassurance, not as thresholds", () => {
    const promise = getReassuranceCaveats("prevent_cancellation_8a");

    expect(promise).toHaveLength(1);
    expect(promise[0]?.text).toContain("không tự xử lý thay");
    expect(
      getPlanCaveats("prevent_cancellation_8a").filter(
        (caveat) => caveat.caveatClass === "threshold-undefined",
      ),
    ).toHaveLength(1);
  });
});

describe("per-class presentation rules", () => {
  it("hides the classes that discriminate nothing and shows the two that do", () => {
    expect(PLAN_CAVEAT_PLACEMENT["threshold-undefined"]).toBe("hidden");
    expect(PLAN_CAVEAT_PLACEMENT["fulfilment-unsupported"]).toBe("hidden");
    expect(PLAN_CAVEAT_PLACEMENT["feature-unavailable"]).toBe(
      "reasoning-expansion",
    );
    expect(PLAN_CAVEAT_PLACEMENT.reassurance).toBe("decision-trust-line");

    expect(isRenderedCaveatClass("threshold-undefined")).toBe(false);
    expect(isRenderedCaveatClass("fulfilment-unsupported")).toBe(false);
    expect(isRenderedCaveatClass("feature-unavailable")).toBe(true);
    expect(isRenderedCaveatClass("reassurance")).toBe(true);
  });

  it("keeps the fulfilment-model data alive for later multi-tenant sign-in", () => {
    // Hidden, not deleted: seven workflows still carry the typed statement.
    const carriers = workflowsCarrying("fulfilment-unsupported");

    expect(carriers).toHaveLength(7);
    for (const workflowKey of carriers) {
      const hidden = getHiddenCaveats(workflowKey);
      expect(
        hidden.some(
          (caveat) => caveat.caveatClass === "fulfilment-unsupported",
        ),
      ).toBe(true);
    }
  });

  it("routes hidden, reasoning and trust-line selectors to disjoint sets", () => {
    for (const workflowKey of Object.keys(WORKFLOW_PLAN_CAVEATS)) {
      const all = getPlanCaveats(workflowKey);
      const hidden = getHiddenCaveats(workflowKey);
      const reasoning = getReasoningCaveats(workflowKey);
      const trust = getReassuranceCaveats(workflowKey);

      expect(hidden.length + reasoning.length + trust.length).toBe(all.length);
      for (const caveat of hidden) {
        expect(isRenderedCaveatClass(caveat.caveatClass)).toBe(false);
      }
      for (const caveat of reasoning) {
        expect(caveat.caveatClass).toBe("feature-unavailable");
      }
      for (const caveat of trust) {
        expect(caveat.caveatClass).toBe("reassurance");
      }
    }
  });

  it("selects by class from an arbitrary caveat list", () => {
    const caveats = getPlanCaveats("delete_activity_7b");

    expect(selectPlanCaveats(caveats, "feature-unavailable")).toHaveLength(1);
    expect(selectPlanCaveats(caveats, "reassurance")).toHaveLength(0);
  });
});

describe("class D as a consumable surface (#775 repeat consent)", () => {
  it("exports the reassurance-carrying workflow keys as a stable list", () => {
    expect([...REASSURANCE_CAVEAT_WORKFLOW_KEYS]).toEqual([
      "prevent_cancellation_8a",
      "prevent_return_8b",
      "prevent_refund_8c",
    ]);
  });

  it("answers the per-workflow question without string parsing", () => {
    for (const workflowKey of Object.keys(WORKFLOW_PLAN_CAVEATS)) {
      expect(hasReassuranceCaveat(workflowKey)).toBe(
        REASSURANCE_CAVEAT_WORKFLOW_KEYS.includes(workflowKey),
      );
    }
  });
});

describe("no system vocabulary in any class", () => {
  it("keeps every caveat text clean, rendered or not", () => {
    for (const workflowKey of Object.keys(WORKFLOW_PLAN_CAVEATS)) {
      for (const caveat of getPlanCaveats(workflowKey)) {
        const rendered = sanitizeSellerReviewText(caveat.text);
        for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
          expect(caveat.text).not.toMatch(pattern);
          expect(rendered).not.toMatch(pattern);
        }
      }
    }
  });

  it("decomposes every multi-statement blob instead of carrying it whole", () => {
    for (const fixture of recommendationFixtures) {
      const caveats = getPlanCaveats(fixture.workflowKey);
      const statements = fixture.knownLimits
        .split(/(?<=\.)\s+/)
        .filter((statement) => statement.trim().length > 0);

      expect(caveats.length).toBeGreaterThanOrEqual(statements.length);

      if (statements.length > 1) {
        for (const caveat of caveats) {
          expect(caveat.text).not.toBe(fixture.knownLimits);
        }
      }
    }
  });
});
