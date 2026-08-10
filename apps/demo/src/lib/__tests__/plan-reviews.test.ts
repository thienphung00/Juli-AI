import { describe, expect, it } from "vitest";

import { getWorkflowPlanReview } from "../plan-reviews";
import { APPROVABLE_WORKFLOW_KEYS } from "../reviews";

describe("getWorkflowPlanReview coverage", () => {
  // Since #910 removed the five-stage review, a key without a plan review
  // falls through to the recoverable not-found state. That silent
  // fallthrough is exactly what hid create_hero_product_1's uploads for an
  // entire wave (#909) — so a workflow added to APPROVABLE_WORKFLOW_KEYS
  // without a registered plan must fail loudly here, not render not-found.
  it("returns a plan review for every approvable workflow key", () => {
    for (const workflowKey of APPROVABLE_WORKFLOW_KEYS) {
      const plan = getWorkflowPlanReview(workflowKey);

      expect(plan, `missing plan review for ${workflowKey}`).not.toBeNull();
      expect(plan?.workflowKey).toBe(workflowKey);
    }
  });
});
