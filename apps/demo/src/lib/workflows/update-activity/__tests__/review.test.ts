import { describe, expect, it } from "vitest";

import { recommendationFixtures } from "../../../recommendations";
import {
  UPDATE_ACTIVITY_WORKFLOW_KEY,
  defaultUpdateActivityAnalyticsMetricKey,
  getUpdateActivityReviewStages,
} from "../review";

describe("getUpdateActivityReviewStages", () => {
  it("returns five stages for workflow 7c with analytics deep-link", () => {
    const stages = getUpdateActivityReviewStages();

    expect(stages.map((stage) => stage.stage)).toEqual([
      "why",
      "analytics",
      "inputs",
      "preview",
      "approve",
    ]);

    const analytics = stages.find((stage) => stage.stage === "analytics");
    expect(analytics?.analyticsMetricHref).toBe(
      `/analytics/${defaultUpdateActivityAnalyticsMetricKey}`,
    );
  });

  it("derives Why-stage copy from the update_activity_7c recommendation fixture", () => {
    const fixture = recommendationFixtures.find(
      (entry) => entry.workflowKey === UPDATE_ACTIVITY_WORKFLOW_KEY,
    );
    expect(fixture).toBeDefined();

    const why = getUpdateActivityReviewStages().find(
      (stage) => stage.stage === "why",
    );

    expect(why?.body).toContain(fixture!.reasoning);
    expect(why?.body).toContain(fixture!.signal);
  });

  it("shows activity_id as read-only with no search affordance", () => {
    const inputs = getUpdateActivityReviewStages().find(
      (stage) => stage.stage === "inputs",
    );

    expect(inputs?.body).toMatch(/không hỗ trợ tìm kiếm/i);
    expect(inputs?.inputFields).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: "activity_id",
          editable: false,
          required: true,
        }),
      ]),
    );
  });

  it("labels FBT promotion scaffold as Unresolved/Unfilled in preview", () => {
    const preview = getUpdateActivityReviewStages().find(
      (stage) => stage.stage === "preview",
    );

    expect(preview?.body).toMatch(/FBT.*Unresolved\/Unfilled/i);
  });
});
