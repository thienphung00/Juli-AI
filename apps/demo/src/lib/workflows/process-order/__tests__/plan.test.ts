import { describe, expect, it } from "vitest";

import { buildAnalyticsMetricHref } from "../../../analytics/main-kpis";
import {
  IMPACT_DIRECTIONAL_GOALS,
  getWorkflowPlanReview,
} from "../../../plan-reviews";
import { recommendationFixtures } from "../../../recommendations";
import { REVIEW_UI_BANNED_PATTERNS } from "../../../review-seller-copy";
import {
  PROCESS_ORDER_WORKFLOW_KEY,
  defaultProcessOrderAnalyticsMetricKey,
} from "../review";
import {
  PROCESS_ORDER_BRANCHES,
  PROCESS_ORDER_BRANCH_SELLER,
  PROCESS_ORDER_BRANCH_TIKTOK,
  PROCESS_ORDER_RECOMMENDED_BRANCH,
  getProcessOrderPlanReview,
} from "../plan";

const fixture = recommendationFixtures.find(
  (entry) => entry.workflowKey === PROCESS_ORDER_WORKFLOW_KEY,
);

/** Every authored string the plan can put in front of a seller, per branch. */
function collectPlanStrings(
  branch: (typeof PROCESS_ORDER_BRANCHES)[number],
): string[] {
  const plan = getProcessOrderPlanReview(branch);
  const options = plan.decision.recommendedOptions;

  return [
    plan.title,
    plan.situation.summary,
    plan.situation.disclosureQuestion,
    ...plan.situation.detailLines,
    plan.impact.directionalGoal,
    plan.decision.proposal,
    plan.decision.reasoning,
    ...(options
      ? [
          options.disclosureQuestion,
          ...options.groups.flatMap((group) => [
            group.label,
            ...group.options.map((option) => option.value),
          ]),
        ]
      : []),
    ...(plan.details?.detailLines ?? []),
  ];
}

describe("getProcessOrderPlanReview", () => {
  it("returns the Situation → Decision → Details spine", () => {
    const plan = getProcessOrderPlanReview();

    expect(plan.workflowKey).toBe(PROCESS_ORDER_WORKFLOW_KEY);
    expect(plan.title).toBe(fixture?.title);
    expect(plan.decision.proposal.trim().length).toBeGreaterThan(0);
    // The Details section is populated here — process_order_5 is the first
    // workflow with branch-gated execution detail.
    expect(plan.details?.detailLines.length).toBeGreaterThan(0);
  });

  it("collapses the three order-context fields into one summary row", () => {
    const plan = getProcessOrderPlanReview();

    expect(plan.situation.summary).toContain("3 thông tin");
    expect(plan.situation.detailLines).toHaveLength(3);
  });

  it("phrases the situation disclosure as a question, not a noun", () => {
    const plan = getProcessOrderPlanReview();

    expect(plan.situation.disclosureQuestion.trim().endsWith("?")).toBe(true);
  });

  it("holds both decision-grade fields as two option groups, without a bespoke layout", () => {
    const options = getProcessOrderPlanReview().decision.recommendedOptions;

    expect(options).toBeDefined();
    expect(options!.disclosureQuestion.trim().endsWith("?")).toBe(true);
    // ADR-055 item 8: the Decision section holds 1–2 items; process_order_5
    // legitimately has two. Two groups in the shared shape, not a new layout.
    expect(options!.groups).toHaveLength(2);
    for (const group of options!.groups) {
      expect(
        group.options.filter((option) => option.proposed),
      ).toHaveLength(1);
    }
  });

  it("states the proposal in a single sentence", () => {
    const sentences = getProcessOrderPlanReview()
      .decision.proposal.split(/[.!?](?:\s|$)/)
      .filter((chunk) => chunk.trim().length > 0);

    expect(sentences).toHaveLength(1);
  });

  it("carries the workflow's pre-authored fixture reasoning verbatim", () => {
    expect(getProcessOrderPlanReview().decision.reasoning).toBe(
      fixture?.reasoning,
    );
  });

  it("ties the impact block to the workflow's existing cancellation-rate binding", () => {
    const plan = getProcessOrderPlanReview();

    expect(plan.impact.metricKey).toBe(defaultProcessOrderAnalyticsMetricKey);
    expect(plan.impact.directionalGoal).toBe(
      IMPACT_DIRECTIONAL_GOALS[defaultProcessOrderAnalyticsMetricKey],
    );
    // Never a projected magnitude (ADR-055 item 16).
    expect(plan.impact.directionalGoal).not.toMatch(/\d/);
  });

  it("resolves the Analytics deep link to the tied cancellation-rate KPI", () => {
    expect(getProcessOrderPlanReview().situation.analyticsMetricHref).toBe(
      buildAnalyticsMetricHref(defaultProcessOrderAnalyticsMetricKey),
    );
  });

  it("pre-commits the TikTok-pickup branch by default", () => {
    expect(PROCESS_ORDER_RECOMMENDED_BRANCH).toBe(PROCESS_ORDER_BRANCH_TIKTOK);
    expect(getProcessOrderPlanReview()).toEqual(
      getProcessOrderPlanReview(PROCESS_ORDER_BRANCH_TIKTOK),
    );
  });

  it("offers exactly the two mutually exclusive branches", () => {
    expect([...PROCESS_ORDER_BRANCHES]).toEqual([
      PROCESS_ORDER_BRANCH_TIKTOK,
      PROCESS_ORDER_BRANCH_SELLER,
    ]);
  });
});

describe("process_order_5 branch discriminator", () => {
  const tiktokDetails = () =>
    getProcessOrderPlanReview(PROCESS_ORDER_BRANCH_TIKTOK).details!.detailLines;
  const sellerDetails = () =>
    getProcessOrderPlanReview(PROCESS_ORDER_BRANCH_SELLER).details!.detailLines;

  it("gates the document and pickup detail behind the TikTok-pickup branch", () => {
    const joined = tiktokDetails().join(" ");

    expect(tiktokDetails()).toHaveLength(2);
    expect(joined).toContain("Hóa đơn thương mại");
    expect(joined).toContain("09:00");
  });

  it("gates the tracking and carrier detail behind the seller-delivery branch", () => {
    const joined = sellerDetails().join(" ");

    expect(sellerDetails()).toHaveLength(2);
    expect(joined).toContain("TK-20260807-001");
    expect(joined).toContain("SP-TKT-01");
  });

  it("keeps each branch's values out of the other branch entirely", () => {
    const tiktokJoined = tiktokDetails().join(" ");
    const sellerJoined = sellerDetails().join(" ");

    expect(tiktokJoined).not.toContain("TK-20260807-001");
    expect(tiktokJoined).not.toContain("SP-TKT-01");
    expect(sellerJoined).not.toContain("Hóa đơn thương mại");
    expect(sellerJoined).not.toContain("09:00");
  });

  it("switches the whole Details section when the discriminator switches", () => {
    // Not a superset and not a merge: the two branches share no detail line,
    // so no abandoned-branch value can survive a switch.
    const overlap = tiktokDetails().filter((line) =>
      sellerDetails().includes(line),
    );

    expect(overlap).toHaveLength(0);
  });

  it("moves the proposed delivery option to whichever branch is chosen", () => {
    for (const branch of PROCESS_ORDER_BRANCHES) {
      const groups =
        getProcessOrderPlanReview(branch).decision.recommendedOptions!.groups;
      // The delivery group is the branch discriminator — the last group.
      const deliveryGroup = groups[groups.length - 1]!;
      const proposed = deliveryGroup.options.filter(
        (option) => option.proposed,
      );

      expect(proposed).toHaveLength(1);
    }

    const tiktokProposed = getProcessOrderPlanReview(
      PROCESS_ORDER_BRANCH_TIKTOK,
    ).decision.recommendedOptions!.groups.at(-1)!
      .options.find((option) => option.proposed)!.value;
    const sellerProposed = getProcessOrderPlanReview(
      PROCESS_ORDER_BRANCH_SELLER,
    ).decision.recommendedOptions!.groups.at(-1)!
      .options.find((option) => option.proposed)!.value;

    expect(tiktokProposed).not.toBe(sellerProposed);
  });

  it("keeps the proposal sentence consistent with the chosen branch", () => {
    const tiktokProposal = getProcessOrderPlanReview(
      PROCESS_ORDER_BRANCH_TIKTOK,
    ).decision.proposal;
    const sellerProposal = getProcessOrderPlanReview(
      PROCESS_ORDER_BRANCH_SELLER,
    ).decision.proposal;

    expect(tiktokProposal).not.toBe(sellerProposal);
  });
});

describe("process_order_5 seller copy", () => {
  it("never carries the risks copy, on either branch", () => {
    expect(fixture?.risks).toBeTruthy();

    for (const branch of PROCESS_ORDER_BRANCHES) {
      for (const text of collectPlanStrings(branch)) {
        expect(text).not.toContain(fixture!.risks);
      }
    }
  });

  it("keeps every plan string free of system vocabulary, on either branch", () => {
    // The five-stage copy leaked ship / split / confirm / Create Packages —
    // none of it may survive into the plan review.
    for (const branch of PROCESS_ORDER_BRANCHES) {
      for (const text of collectPlanStrings(branch)) {
        for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
          expect(text).not.toMatch(pattern);
        }
      }
    }
  });
});

describe("getWorkflowPlanReview routing for process_order_5", () => {
  it("routes process_order_5 to its plan review", () => {
    expect(getWorkflowPlanReview(PROCESS_ORDER_WORKFLOW_KEY)).not.toBeNull();
  });
});
