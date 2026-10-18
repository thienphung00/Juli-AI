import { describe, expect, it } from "vitest";

import { REASSURANCE_CAVEAT_WORKFLOW_KEYS } from "../lib/plan-caveats";
import { recommendationFixtures } from "../lib/recommendations";
import {
  REPEAT_CONSENT_ELIGIBILITY,
  REPEAT_CONSENT_ELIGIBLE_WORKFLOW_KEYS,
  REPEAT_CONSENT_EXCLUDED_WORKFLOW_KEYS,
  REPEAT_CONSENT_GRANTED_MODE,
  REPEAT_CONSENT_MODES,
  getRepeatConsentExclusionNote,
  isRepeatConsentEligible,
  shouldOfferRepeatConsent,
} from "../lib/repeat-consent";

/**
 * P53: the rendered repeat-consent tests went with the only surfaces that
 * mounted `RepeatConsentBlock` (the legacy `/decisions/in-progress/*` detail
 * view and `InProgressPanel`). The block and `lib/repeat-consent.ts` are kept
 * untouched (consent code, TOO-RISKY in the 2026-10-18 audit); this file keeps
 * the pure eligibility table and gate derivation.
 */

/**
 * The eligibility table transcribed from issue #775 / ADR-055 item 19. It is
 * the source of truth: repeat consent is excluded wherever shipped seller copy
 * already promises Juli will not act unaided, and those promises live in
 * `risks` as often as in `knownLimits`.
 */
const EXPECTED_EXCLUDED = [
  "prevent_cancellation_8a",
  "prevent_return_8b",
  "clear_excess_4",
  "create_activity_7a",
  "replenish_inventory_3",
  "create_hero_product_1",
] as const;

const EXPECTED_ELIGIBLE = [
  "optimize_product_2",
  "process_order_5",
  "delete_activity_7b",
  "prevent_refund_8c",
  "update_activity_7c",
] as const;

describe("repeat consent — eligibility table (DPR-16, issue #775)", () => {
  it("encodes the full eligibility table explicitly, one entry per shipped workflow", () => {
    expect(REPEAT_CONSENT_ELIGIBILITY).toEqual({
      create_hero_product_1: false,
      optimize_product_2: true,
      replenish_inventory_3: false,
      clear_excess_4: false,
      process_order_5: true,
      create_activity_7a: false,
      update_activity_7c: true,
      delete_activity_7b: true,
      prevent_cancellation_8a: false,
      prevent_return_8b: false,
      prevent_refund_8c: true,
    });
  });

  it("covers every shipped workflow fixture — no workflow is left unclassified", () => {
    const fixtureKeys = recommendationFixtures.map(
      (fixture) => fixture.workflowKey,
    );

    for (const workflowKey of fixtureKeys) {
      expect(
        Object.prototype.hasOwnProperty.call(
          REPEAT_CONSENT_ELIGIBILITY,
          workflowKey,
        ),
        `Workflow ${workflowKey} is missing from the repeat-consent eligibility table`,
      ).toBe(true);
    }

    expect(Object.keys(REPEAT_CONSENT_ELIGIBILITY).sort()).toEqual(
      [...fixtureKeys].sort(),
    );
  });

  it("exposes exactly the five eligible and six excluded workflow kinds", () => {
    expect([...REPEAT_CONSENT_ELIGIBLE_WORKFLOW_KEYS].sort()).toEqual(
      [...EXPECTED_ELIGIBLE].sort(),
    );
    expect([...REPEAT_CONSENT_EXCLUDED_WORKFLOW_KEYS].sort()).toEqual(
      [...EXPECTED_EXCLUDED].sort(),
    );
  });

  it("states a reason for every exclusion — nothing is excluded silently", () => {
    for (const workflowKey of EXPECTED_EXCLUDED) {
      expect(
        getRepeatConsentExclusionNote(workflowKey),
        `Excluded workflow ${workflowKey} carries no stated reason`,
      ).not.toBe("");
    }
    for (const workflowKey of EXPECTED_ELIGIBLE) {
      expect(getRepeatConsentExclusionNote(workflowKey)).toBe("");
    }
  });

  it("answers isRepeatConsentEligible per the table, and denies unknown workflows by default", () => {
    for (const workflowKey of EXPECTED_ELIGIBLE) {
      expect(isRepeatConsentEligible(workflowKey)).toBe(true);
    }
    for (const workflowKey of EXPECTED_EXCLUDED) {
      expect(isRepeatConsentEligible(workflowKey)).toBe(false);
    }
    expect(isRepeatConsentEligible("some_future_workflow_99")).toBe(false);
  });

  /**
   * Cross-reference only. Class D (`reassurance`) is derived from `knownLimits`
   * alone, while ADR-055 item 19 puts blocking promises in `risks` just as
   * often — so the two sets genuinely disagree and eligibility must NOT be
   * derived from class D. This test pins the known disagreement so that a
   * future edit to either side is a deliberate, visible decision.
   */
  it("does not derive eligibility from the class-D caveat set, and pins the known disagreement", () => {
    expect([...REASSURANCE_CAVEAT_WORKFLOW_KEYS].sort()).toEqual([
      "prevent_cancellation_8a",
      "prevent_refund_8c",
      "prevent_return_8b",
    ]);

    // Class-D but ELIGIBLE — class D would have wrongly excluded it.
    expect(REASSURANCE_CAVEAT_WORKFLOW_KEYS).toContain("prevent_refund_8c");
    expect(isRepeatConsentEligible("prevent_refund_8c")).toBe(true);

    // Excluded without being class-D — class D would have wrongly included them.
    for (const workflowKey of [
      "clear_excess_4",
      "create_activity_7a",
      "replenish_inventory_3",
    ]) {
      expect(REASSURANCE_CAVEAT_WORKFLOW_KEYS).not.toContain(workflowKey);
      expect(isRepeatConsentEligible(workflowKey)).toBe(false);
    }
  });
});

describe("repeat consent — the three gates as pure derivation", () => {
  const base = {
    workflowKey: "optimize_product_2",
    lifecycleStatus: "completed" as const,
    promptedWorkflowKeys: [] as string[],
    grants: {},
  };

  it("offers on a completed, eligible, not-yet-asked workflow", () => {
    expect(shouldOfferRepeatConsent(base)).toBe(true);
  });

  it("OUTCOME — never offers on needs_input or executing", () => {
    expect(
      shouldOfferRepeatConsent({ ...base, lifecycleStatus: "needs_input" }),
    ).toBe(false);
    expect(
      shouldOfferRepeatConsent({ ...base, lifecycleStatus: "executing" }),
    ).toBe(false);
  });

  it("FREQUENCY — never offers a workflow kind that was already asked", () => {
    expect(
      shouldOfferRepeatConsent({
        ...base,
        promptedWorkflowKeys: ["optimize_product_2"],
      }),
    ).toBe(false);
  });

  it("FREQUENCY — never re-offers a kind that already carries a grant record", () => {
    expect(
      shouldOfferRepeatConsent({
        ...base,
        grants: {
          optimize_product_2: {
            workflowKey: "optimize_product_2",
            mode: REPEAT_CONSENT_GRANTED_MODE,
            status: "granted" as const,
            grantedAt: "2026-07-16T04:20:00.000Z",
            withdrawnAt: null,
          },
        },
      }),
    ).toBe(false);
  });

  it("FREQUENCY — a withdrawal does not re-open the prompt", () => {
    expect(
      shouldOfferRepeatConsent({
        ...base,
        promptedWorkflowKeys: ["optimize_product_2"],
        grants: {
          optimize_product_2: {
            workflowKey: "optimize_product_2",
            mode: REPEAT_CONSENT_GRANTED_MODE,
            status: "withdrawn" as const,
            grantedAt: "2026-07-16T04:20:00.000Z",
            withdrawnAt: "2026-07-16T05:00:00.000Z",
          },
        },
      }),
    ).toBe(false);
  });

  it("ELIGIBILITY — never offers on any of the six excluded workflows, even when completed", () => {
    for (const workflowKey of EXPECTED_EXCLUDED) {
      expect(
        shouldOfferRepeatConsent({ ...base, workflowKey }),
        `Repeat consent must never be offered on excluded workflow ${workflowKey}`,
      ).toBe(false);
    }
  });

  it("offers on each of the five eligible workflows when completed", () => {
    for (const workflowKey of EXPECTED_ELIGIBLE) {
      expect(
        shouldOfferRepeatConsent({ ...base, workflowKey }),
        `Repeat consent should be offered on eligible workflow ${workflowKey}`,
      ).toBe(true);
    }
  });
});

describe("repeat consent — what granting means", () => {
  it("has exactly one grantable mode, and it is pre-approval with notification", () => {
    expect(REPEAT_CONSENT_MODES).toHaveLength(1);
    expect(REPEAT_CONSENT_MODES).toEqual(["pre_approved_with_notification"]);
    expect(REPEAT_CONSENT_GRANTED_MODE).toBe("pre_approved_with_notification");
  });
});
