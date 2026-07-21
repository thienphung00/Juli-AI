import { describe, expect, it } from "vitest";

import { recommendationFixtures } from "../../../recommendations";
import {
  CREATE_ACTIVITY_WORKFLOW_KEY,
  defaultCreateActivityAnalyticsMetricKey,
  getCreateActivityReviewStages,
} from "../review";

describe("getCreateActivityReviewStages", () => {
  it("returns five stages for workflow 7a with analytics deep-link", () => {
    const stages = getCreateActivityReviewStages();

    expect(stages.map((stage) => stage.stage)).toEqual([
      "why",
      "analytics",
      "inputs",
      "preview",
      "approve",
    ]);

    const analytics = stages.find((stage) => stage.stage === "analytics");
    expect(analytics?.analyticsMetricHref).toBe(
      `/analytics/${defaultCreateActivityAnalyticsMetricKey}`,
    );
  });

  it("derives Why-stage copy from the create_activity_7a recommendation fixture", () => {
    const fixture = recommendationFixtures.find(
      (entry) => entry.workflowKey === CREATE_ACTIVITY_WORKFLOW_KEY,
    );
    expect(fixture).toBeDefined();

    const why = getCreateActivityReviewStages().find(
      (stage) => stage.stage === "why",
    );

    expect(why?.body).toContain(fixture!.reasoning);
    expect(why?.body).toContain(fixture!.signal);
    expect(why?.body).toContain(fixture!.evidence);
    expect(why?.body).toContain(fixture!.risks);
  });

  it("requires shop-confirmed promotion inputs without invented discount defaults", () => {
    const inputs = getCreateActivityReviewStages().find(
      (stage) => stage.stage === "inputs",
    );

    expect(inputs?.inputFields).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: "activity_type",
          prefillValue: "",
          required: true,
          editable: true,
        }),
        expect.objectContaining({
          key: "discount_config",
          prefillValue: "",
          required: true,
          editable: true,
        }),
        expect.objectContaining({
          key: "skus",
          required: true,
          editable: true,
        }),
      ]),
    );
  });

  it("labels FBT promotion scaffold as Unresolved/Unfilled in preview", () => {
    const fixture = recommendationFixtures.find(
      (entry) => entry.workflowKey === CREATE_ACTIVITY_WORKFLOW_KEY,
    );
    const preview = getCreateActivityReviewStages().find(
      (stage) => stage.stage === "preview",
    );

    expect(preview?.body).toContain(fixture!.toolName);
    expect(preview?.body).toContain(fixture!.capabilityLabel);
    expect(preview?.body).toContain(fixture!.knownLimits);
    expect(preview?.body).toMatch(/FBT.*Unresolved\/Unfilled/i);
  });
});
