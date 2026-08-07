import type { PlanReviewContent } from "../../plan-reviews";

import { recommendationFixtures } from "../../recommendations";
import {
  DELETE_ACTIVITY_WORKFLOW_KEY,
  defaultDeleteActivityAnalyticsMetricKey,
} from "./review";

const fixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === DELETE_ACTIVITY_WORKFLOW_KEY,
);

if (!fixtureEntry) {
  throw new Error("Missing delete_activity_7b recommendation fixture");
}

const deleteActivityFixture = fixtureEntry;

/**
 * Situation → Decision → Details plan review for `delete_activity_7b`
 * (ADR-055 items 1, 8, 13; scope cuts per item 14 — no risks display, no
 * decision-options editing). The workflow has one known field and one
 * decision, and no branch-gated detail, so `details` is deliberately absent.
 */
export function getDeleteActivityPlanReview(): PlanReviewContent {
  return {
    workflowKey: DELETE_ACTIVITY_WORKFLOW_KEY,
    title: deleteActivityFixture.title,
    situation: {
      summary: "Chương trình “Giảm giá trực tiếp mùa hè” · 1 thông tin",
      disclosureQuestion: "Juli dựa vào thông tin nào?",
      detailLines: [
        "Juli đang theo dõi chương trình ACT-7720 — “Giảm giá trực tiếp mùa hè” (đang hoạt động).",
      ],
      analyticsMetricHref: `/analytics/${defaultDeleteActivityAnalyticsMetricKey}`,
    },
    decision: {
      proposal:
        "Juli đề xuất kết thúc chương trình “Giảm giá trực tiếp mùa hè” vì đã hết hiệu lực, để tránh giảm giá ngoài ý muốn.",
      // The workflow's pre-authored reasoning from the shared fixture table —
      // revealed behind the question-labelled disclosure, sanitized at render.
      reasoning: deleteActivityFixture.reasoning,
    },
    // No `details` key: delete_activity_7b has no branch-gated detail, so the
    // Details section renders as nothing — never an empty stub.
  };
}
