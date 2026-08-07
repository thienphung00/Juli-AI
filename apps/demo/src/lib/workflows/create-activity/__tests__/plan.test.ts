import { describe, expect, it } from "vitest";

import { buildAnalyticsMetricHref } from "../../../analytics/main-kpis";
import { recommendationFixtures } from "../../../recommendations";
import { REVIEW_UI_BANNED_PATTERNS } from "../../../review-seller-copy";
import {
  IMPACT_DIRECTIONAL_GOALS,
  getWorkflowPlanReview,
} from "../../../plan-reviews";
import {
  CREATE_ACTIVITY_WORKFLOW_KEY,
  defaultCreateActivityAnalyticsMetricKey,
} from "../review";
import { getCreateActivityPlanReview } from "../plan";

const fixture = recommendationFixtures.find(
  (entry) => entry.workflowKey === CREATE_ACTIVITY_WORKFLOW_KEY,
);

function collectPlanStrings(): string[] {
  const plan = getCreateActivityPlanReview();
  return [
    plan.title,
    plan.decision.proposal,
    plan.decision.reasoning,
    plan.impact.directionalGoal,
    plan.situation.summary,
    plan.situation.disclosureQuestion,
    ...plan.situation.detailLines,
    ...(plan.details?.detailLines ?? []),
  ];
}

describe("getCreateActivityPlanReview", () => {
  it("returns the full Situation → Decision → Details spine", () => {
    const plan = getCreateActivityPlanReview();

    expect(plan.workflowKey).toBe(CREATE_ACTIVITY_WORKFLOW_KEY);
    expect(plan.title).toBe(fixture?.title);
    expect(plan.decision.proposal.trim().length).toBeGreaterThan(0);
    // Four decided fields: the window and the product specifics are
    // branch-gated into Details rather than stacked into the Decision.
    expect(plan.details).toBeDefined();
    expect(plan.details!.detailLines.length).toBeGreaterThan(0);
  });

  it("states the proposal in exactly one sentence", () => {
    const plan = getCreateActivityPlanReview();

    const sentences = plan.decision.proposal
      .split(/[.!?](?:\s|$)/)
      .filter((chunk) => chunk.trim().length > 0);
    expect(sentences).toHaveLength(1);
  });

  it("collapses the single known field into a count, not labelled read-only fields", () => {
    const plan = getCreateActivityPlanReview();

    expect(plan.situation.summary).toContain("1 thông tin");
    expect(plan.situation.detailLines).toHaveLength(1);
  });

  it("keeps the Decision legible: the branch discriminator and the discount only", () => {
    const plan = getCreateActivityPlanReview();
    const details = plan.details?.detailLines.join(" ") ?? "";

    // Branch discriminator + discount rest in the Decision sentence …
    expect(plan.decision.proposal).toContain("giảm giá trực tiếp");
    expect(plan.decision.proposal).toContain("15%");
    // … the remaining decided fields are gated into Details, never stacked.
    expect(plan.decision.proposal).not.toContain("PRD-77201");
    expect(plan.decision.proposal).not.toContain("10/08/2026");
    expect(details).toContain("PRD-77201");
    expect(details).toContain("PRD-77202");
    expect(details).toContain("10/08/2026");
    expect(details).toContain("24/08/2026");
  });

  it("phrases the situation disclosure as a question", () => {
    const plan = getCreateActivityPlanReview();

    expect(plan.situation.disclosureQuestion.trim().endsWith("?")).toBe(true);
  });

  it("carries the workflow's reasoning behind the decision disclosure — never empty", () => {
    const plan = getCreateActivityPlanReview();

    expect(plan.decision.reasoning).toBe(fixture?.reasoning);
    expect(plan.decision.reasoning.trim().length).toBeGreaterThan(0);
  });

  it("ties the impact block to the workflow's existing Main KPI with no magnitude", () => {
    const plan = getCreateActivityPlanReview();

    expect(plan.impact.metricKey).toBe(defaultCreateActivityAnalyticsMetricKey);
    expect(plan.impact.directionalGoal).toBe(
      IMPACT_DIRECTIONAL_GOALS[defaultCreateActivityAnalyticsMetricKey],
    );
    expect(plan.impact.directionalGoal).not.toMatch(/\d/);
  });

  it("does not carry the risks copy anywhere in the plan", () => {
    expect(fixture?.risks).toBeTruthy();
    for (const text of collectPlanStrings()) {
      expect(text).not.toContain(fixture!.risks);
    }
  });

  it("does not render the promotion-search limitation in this plan", () => {
    // The gap lives in the fixture's knownLimits and its presentation is owned
    // by the typed-caveat slice — it must not surface anywhere here.
    expect(fixture?.knownLimits).toContain("theo từ khoá chưa được hỗ trợ");
    for (const text of collectPlanStrings()) {
      expect(text).not.toMatch(/tìm kiếm|từ khoá|chưa được hỗ trợ/i);
    }
  });

  it("keeps every plan string free of system vocabulary", () => {
    for (const text of collectPlanStrings()) {
      for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
        expect(text).not.toMatch(pattern);
      }
    }
  });

  it("links the situation expansion to the tied CTOR metric", () => {
    const plan = getCreateActivityPlanReview();

    expect(defaultCreateActivityAnalyticsMetricKey).toBe("ctor");
    expect(plan.situation.analyticsMetricHref).toBe(
      buildAnalyticsMetricHref(defaultCreateActivityAnalyticsMetricKey),
    );
  });

  it("is served by the plan review registry", () => {
    expect(getWorkflowPlanReview(CREATE_ACTIVITY_WORKFLOW_KEY)?.workflowKey).toBe(
      CREATE_ACTIVITY_WORKFLOW_KEY,
    );
  });
});
