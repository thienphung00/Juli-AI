import { describe, expect, it } from "vitest";

import { recommendationFixtures } from "../../../recommendations";
import { REVIEW_UI_BANNED_PATTERNS } from "../../../review-seller-copy";
import {
  DELETE_ACTIVITY_WORKFLOW_KEY,
  defaultDeleteActivityAnalyticsMetricKey,
  getDeleteActivityReviewStages,
} from "../review";

describe("getDeleteActivityReviewStages", () => {
  it("returns five stages for workflow 7b with analytics deep-link", () => {
    const stages = getDeleteActivityReviewStages();

    expect(stages.map((stage) => stage.stage)).toEqual([
      "why",
      "analytics",
      "inputs",
      "preview",
      "approve",
    ]);

    const analytics = stages.find((stage) => stage.stage === "analytics");
    expect(analytics?.analyticsMetricHref).toBe(
      `/analytics/${defaultDeleteActivityAnalyticsMetricKey}`,
    );
  });

  it("derives Why-stage copy from the delete_activity_7b recommendation fixture", () => {
    const fixture = recommendationFixtures.find(
      (entry) => entry.workflowKey === DELETE_ACTIVITY_WORKFLOW_KEY,
    );
    expect(fixture).toBeDefined();

    const why = getDeleteActivityReviewStages().find(
      (stage) => stage.stage === "why",
    );

    expect(why?.body).toContain(fixture!.reasoning);
    expect(why?.body).toContain(fixture!.signal);
  });

  it("limits inputs to read-only activity_id and confirmation — no configurable payload", () => {
    const inputs = getDeleteActivityReviewStages().find(
      (stage) => stage.stage === "inputs",
    );

    expect(inputs?.body).toMatch(/không có cấu hình thêm/i);
    expect(inputs?.inputFields?.map((field) => field.key)).toEqual([
      "activity_id",
      "confirm_end",
    ]);
    expect(
      inputs?.inputFields?.find((field) => field.key === "activity_id"),
    ).toMatchObject({ editable: false });
  });

  it("uses seller-language preview without backend jargon", () => {
    const fixture = recommendationFixtures.find(
      (entry) => entry.workflowKey === DELETE_ACTIVITY_WORKFLOW_KEY,
    );
    const preview = getDeleteActivityReviewStages().find(
      (stage) => stage.stage === "preview",
    );

    expect(preview?.body).toContain(fixture!.sellerReason);
    for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
      expect(preview?.body ?? "").not.toMatch(pattern);
    }
  });
});
