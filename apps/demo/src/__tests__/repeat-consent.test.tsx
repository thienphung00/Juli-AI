import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ExecutionRecord } from "@juli/contracts";

import { InProgressDetailView } from "../app/decisions/in-progress/[executionId]/page";
import {
  DEFAULT_MUTABLE_MOCK_STATE,
  DEMO_MUTABLE_STATE_STORAGE_KEY,
  DemoStateProvider,
} from "../components/demo-state";
import { InProgressPanel } from "../components/in-progress-panel";
import { RecommendationReview } from "../components/recommendation-review";
import {
  createHeroProductTimeline,
  resetExecutionCountersForTests,
} from "../lib/executions";
import { REASSURANCE_CAVEAT_WORKFLOW_KEYS } from "../lib/plan-caveats";
import { recommendationFixtures } from "../lib/recommendations";
import {
  REPEAT_CONSENT_COPY,
  REPEAT_CONSENT_ELIGIBILITY,
  REPEAT_CONSENT_ELIGIBLE_WORKFLOW_KEYS,
  REPEAT_CONSENT_EXCLUDED_WORKFLOW_KEYS,
  REPEAT_CONSENT_GRANTED_MODE,
  REPEAT_CONSENT_MODES,
  getRepeatConsentExclusionNote,
  isRepeatConsentEligible,
  shouldOfferRepeatConsent,
} from "../lib/repeat-consent";
import { REVIEW_UI_BANNED_PATTERNS } from "../lib/review-seller-copy";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => "/decisions"),
  useParams: vi.fn(() => ({ executionId: "unused" })),
  useRouter: vi.fn(() => ({
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
    push,
    refresh: vi.fn(),
    replace: vi.fn(),
  })),
}));

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

function buildRecord(
  overrides: Pick<ExecutionRecord, "executionId"> & Partial<ExecutionRecord>,
): ExecutionRecord {
  const lifecycleStatus = overrides.lifecycleStatus ?? "completed";
  const timeline = (overrides.timeline ?? createHeroProductTimeline()).map(
    (step) =>
      lifecycleStatus === "completed"
        ? { ...step, status: "succeeded" as const }
        : step,
  );

  return {
    workflowKey: "optimize_product_2",
    toolName: "listing.optimize_product",
    startedAt: "2026-07-16T04:12:00.000Z",
    updatedAt: "2026-07-16T04:20:00.000Z",
    approvedInputs: {},
    ...overrides,
    lifecycleStatus,
    timeline,
  };
}

function seedMutableState(
  records: ExecutionRecord[],
  extra: Record<string, unknown> = {},
) {
  localStorage.setItem(
    DEMO_MUTABLE_STATE_STORAGE_KEY,
    JSON.stringify({
      ...DEFAULT_MUTABLE_MOCK_STATE,
      decisionsView: "in-progress",
      executionRecords: Object.fromEntries(
        records.map((record) => [record.executionId, record]),
      ),
      executionProgress: Object.fromEntries(
        records.map((record) => [record.executionId, record.lifecycleStatus]),
      ),
      ...extra,
    }),
  );
}

function renderPanel() {
  return render(
    <DemoStateProvider>
      <InProgressPanel panelId="in-progress-panel" />
    </DemoStateProvider>,
  );
}

function readPersistedState(): Record<string, unknown> {
  return JSON.parse(
    localStorage.getItem(DEMO_MUTABLE_STATE_STORAGE_KEY) ?? "{}",
  ) as Record<string, unknown>;
}

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

describe("repeat consent — rendered on the execution surface", () => {
  beforeEach(() => {
    localStorage.clear();
    resetExecutionCountersForTests();
    push.mockClear();
  });

  it("asks after a completed, eligible workflow", async () => {
    seedMutableState([
      buildRecord({
        executionId: "exec-completed-eligible-1",
        workflowKey: "optimize_product_2",
        lifecycleStatus: "completed",
      }),
    ]);

    renderPanel();

    await waitFor(() => {
      expect(screen.getByTestId("repeat-consent-prompt")).toBeInTheDocument();
    });

    const prompt = screen.getByTestId("repeat-consent-prompt");
    expect(
      within(prompt).getByText(REPEAT_CONSENT_COPY.promptTitle),
    ).toBeInTheDocument();
    expect(
      within(prompt).getByRole("button", {
        name: REPEAT_CONSENT_COPY.grantLabel,
      }),
    ).toBeInTheDocument();
    expect(
      within(prompt).getByRole("button", {
        name: REPEAT_CONSENT_COPY.declineLabel,
      }),
    ).toBeInTheDocument();
  });

  it("never asks after needs_input, even on an eligible workflow", async () => {
    seedMutableState([
      buildRecord({
        executionId: "exec-needs-input-eligible-1",
        workflowKey: "optimize_product_2",
        lifecycleStatus: "needs_input",
      }),
    ]);

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText("Cần thêm thông tin")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("repeat-consent-prompt")).not.toBeInTheDocument();
  });

  it("never asks while a workflow is still executing", async () => {
    seedMutableState([
      buildRecord({
        executionId: "exec-executing-eligible-1",
        workflowKey: "optimize_product_2",
        lifecycleStatus: "executing",
      }),
    ]);

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText("Đang thực hiện")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("repeat-consent-prompt")).not.toBeInTheDocument();
  });

  it("never asks on any excluded workflow, even after it completes", async () => {
    for (const workflowKey of EXPECTED_EXCLUDED) {
      localStorage.clear();
      seedMutableState([
        buildRecord({
          executionId: `exec-excluded-${workflowKey}`,
          workflowKey,
          lifecycleStatus: "completed",
        }),
      ]);

      const view = renderPanel();

      await waitFor(() => {
        expect(screen.getByText("Hoàn tất")).toBeInTheDocument();
      });

      expect(
        screen.queryByTestId("repeat-consent-prompt"),
        `Repeat consent prompt must not render for excluded workflow ${workflowKey}`,
      ).not.toBeInTheDocument();
      expect(
        screen.queryByText(REPEAT_CONSENT_COPY.promptTitle),
        `Repeat consent copy leaked onto excluded workflow ${workflowKey}`,
      ).not.toBeInTheDocument();

      view.unmount();
    }
  });

  it("asks on each of the five eligible workflows after they complete", async () => {
    for (const workflowKey of EXPECTED_ELIGIBLE) {
      localStorage.clear();
      seedMutableState([
        buildRecord({
          executionId: `exec-eligible-${workflowKey}`,
          workflowKey,
          lifecycleStatus: "completed",
        }),
      ]);

      const view = renderPanel();

      await waitFor(() => {
        expect(
          screen.getByTestId("repeat-consent-prompt"),
          `Repeat consent prompt should render for eligible workflow ${workflowKey}`,
        ).toBeInTheDocument();
      });

      view.unmount();
    }
  });

  it("asks once per workflow kind, not once per execution", async () => {
    seedMutableState([
      buildRecord({
        executionId: "exec-kind-1",
        workflowKey: "optimize_product_2",
        lifecycleStatus: "completed",
      }),
      buildRecord({
        executionId: "exec-kind-2",
        workflowKey: "optimize_product_2",
        lifecycleStatus: "completed",
      }),
      buildRecord({
        executionId: "exec-kind-3",
        workflowKey: "process_order_5",
        lifecycleStatus: "completed",
      }),
    ]);

    renderPanel();

    await waitFor(() => {
      expect(screen.getAllByTestId("repeat-consent-prompt")).toHaveLength(2);
    });

    // Two kinds completed across three executions — two prompts, never three.
    const prompts = screen.getAllByTestId("repeat-consent-prompt");
    const promptedKinds = prompts.map((prompt) =>
      prompt.getAttribute("data-workflow-kind"),
    );
    expect([...promptedKinds].sort()).toEqual([
      "optimize_product_2",
      "process_order_5",
    ]);
  });

  it("stops asking for that kind once the seller answers, on every other execution of it", async () => {
    const user = userEvent.setup();

    seedMutableState([
      buildRecord({
        executionId: "exec-answer-1",
        workflowKey: "optimize_product_2",
        lifecycleStatus: "completed",
      }),
      buildRecord({
        executionId: "exec-answer-2",
        workflowKey: "optimize_product_2",
        lifecycleStatus: "completed",
      }),
    ]);

    renderPanel();

    await waitFor(() => {
      expect(screen.getByTestId("repeat-consent-prompt")).toBeInTheDocument();
    });

    await user.click(
      screen.getByRole("button", { name: REPEAT_CONSENT_COPY.declineLabel }),
    );

    await waitFor(() => {
      expect(
        screen.queryByTestId("repeat-consent-prompt"),
      ).not.toBeInTheDocument();
    });

    // Declining records the kind as asked; nothing standing is created.
    const state = readPersistedState();
    expect(state.repeatConsentPromptedWorkflowKeys).toEqual([
      "optimize_product_2",
    ]);
    expect(state.repeatConsentGrants).toEqual({});
    expect(screen.queryByTestId("repeat-consent-granted")).not.toBeInTheDocument();
  });
});

describe("repeat consent — what granting means", () => {
  beforeEach(() => {
    localStorage.clear();
    resetExecutionCountersForTests();
    push.mockClear();
  });

  it("has exactly one grantable mode, and it is pre-approval with notification", () => {
    expect(REPEAT_CONSENT_MODES).toHaveLength(1);
    expect(REPEAT_CONSENT_MODES).toEqual(["pre_approved_with_notification"]);
    expect(REPEAT_CONSENT_GRANTED_MODE).toBe("pre_approved_with_notification");
  });

  it("restates the standing permission in plain terms once granted", async () => {
    const user = userEvent.setup();

    seedMutableState([
      buildRecord({
        executionId: "exec-grant-1",
        workflowKey: "optimize_product_2",
        lifecycleStatus: "completed",
      }),
    ]);

    renderPanel();

    await waitFor(() => {
      expect(screen.getByTestId("repeat-consent-prompt")).toBeInTheDocument();
    });

    await user.click(
      screen.getByRole("button", { name: REPEAT_CONSENT_COPY.grantLabel }),
    );

    const granted = await screen.findByTestId("repeat-consent-granted");

    expect(
      within(granted).getByText(REPEAT_CONSENT_COPY.grantedTitle),
    ).toBeInTheDocument();

    // Every plain-terms line of the standing permission is restated.
    for (const term of REPEAT_CONSENT_COPY.grantedTerms) {
      expect(within(granted).getByText(term)).toBeInTheDocument();
    }

    // The prompt is replaced, never left alongside the restatement.
    expect(screen.queryByTestId("repeat-consent-prompt")).not.toBeInTheDocument();
  });

  it("stores the grant as pre-approval with notification — there is no silent-automation path", async () => {
    const user = userEvent.setup();

    seedMutableState([
      buildRecord({
        executionId: "exec-grant-2",
        workflowKey: "process_order_5",
        lifecycleStatus: "completed",
      }),
    ]);

    renderPanel();

    await waitFor(() => {
      expect(screen.getByTestId("repeat-consent-prompt")).toBeInTheDocument();
    });

    await user.click(
      screen.getByRole("button", { name: REPEAT_CONSENT_COPY.grantLabel }),
    );

    await screen.findByTestId("repeat-consent-granted");

    const state = readPersistedState();
    const grants = state.repeatConsentGrants as Record<
      string,
      { mode: string; status: string }
    >;

    expect(Object.keys(grants)).toEqual(["process_order_5"]);
    expect(grants.process_order_5.mode).toBe("pre_approved_with_notification");
    expect(grants.process_order_5.status).toBe("granted");

    // Every stored grant carries the notification mode — no other mode exists.
    for (const grant of Object.values(grants)) {
      expect(REPEAT_CONSENT_MODES).toContain(grant.mode);
    }

    // The granted surface states the notification promise on its face.
    const granted = screen.getByTestId("repeat-consent-granted");
    expect(granted.textContent ?? "").toContain(
      REPEAT_CONSENT_COPY.notificationTerm,
    );
  });

  it("withdraws in one action, with immediate effect and no further approval", async () => {
    const user = userEvent.setup();

    seedMutableState([
      buildRecord({
        executionId: "exec-withdraw-1",
        workflowKey: "delete_activity_7b",
        lifecycleStatus: "completed",
      }),
    ]);

    renderPanel();

    await waitFor(() => {
      expect(screen.getByTestId("repeat-consent-prompt")).toBeInTheDocument();
    });

    await user.click(
      screen.getByRole("button", { name: REPEAT_CONSENT_COPY.grantLabel }),
    );
    await screen.findByTestId("repeat-consent-granted");

    await user.click(
      screen.getByRole("button", { name: REPEAT_CONSENT_COPY.withdrawLabel }),
    );

    // No second confirmation of any kind stands between the seller and withdrawal.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await waitFor(() => {
      expect(
        screen.queryByTestId("repeat-consent-granted"),
      ).not.toBeInTheDocument();
    });

    expect(
      screen.getByTestId("repeat-consent-withdrawn"),
    ).toHaveTextContent(REPEAT_CONSENT_COPY.withdrawnNotice);

    const state = readPersistedState();
    const grants = state.repeatConsentGrants as Record<
      string,
      { status: string; withdrawnAt: string | null }
    >;
    expect(grants.delete_activity_7b.status).toBe("withdrawn");
    expect(grants.delete_activity_7b.withdrawnAt).not.toBeNull();

    // Withdrawal does not re-open the ask.
    expect(screen.queryByTestId("repeat-consent-prompt")).not.toBeInTheDocument();
  });

  it("restates and offers withdrawal on the execution detail view too", async () => {
    seedMutableState(
      [
        buildRecord({
          executionId: "exec-detail-granted-1",
          workflowKey: "update_activity_7c",
          lifecycleStatus: "completed",
        }),
      ],
      {
        repeatConsentPromptedWorkflowKeys: ["update_activity_7c"],
        repeatConsentGrants: {
          update_activity_7c: {
            workflowKey: "update_activity_7c",
            mode: "pre_approved_with_notification",
            status: "granted",
            grantedAt: "2026-07-16T04:20:00.000Z",
            withdrawnAt: null,
          },
        },
      },
    );

    render(
      <DemoStateProvider>
        <InProgressDetailView executionId="exec-detail-granted-1" />
      </DemoStateProvider>,
    );

    const granted = await screen.findByTestId("repeat-consent-granted");
    expect(
      within(granted).getByRole("button", {
        name: REPEAT_CONSENT_COPY.withdrawLabel,
      }),
    ).toBeInTheDocument();
  });

  it("renders no system vocabulary anywhere on the prompt or the granted state", async () => {
    const user = userEvent.setup();

    seedMutableState([
      buildRecord({
        executionId: "exec-copy-guard-1",
        workflowKey: "prevent_refund_8c",
        lifecycleStatus: "completed",
      }),
    ]);

    renderPanel();

    const prompt = await screen.findByTestId("repeat-consent-prompt");
    for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
      expect(
        (prompt.textContent ?? "").match(pattern),
        `Banned pattern on the repeat-consent prompt: ${pattern}`,
      ).toBeNull();
    }

    await user.click(
      screen.getByRole("button", { name: REPEAT_CONSENT_COPY.grantLabel }),
    );

    const granted = await screen.findByTestId("repeat-consent-granted");
    for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
      expect(
        (granted.textContent ?? "").match(pattern),
        `Banned pattern on the repeat-consent granted state: ${pattern}`,
      ).toBeNull();
    }

    await user.click(
      screen.getByRole("button", { name: REPEAT_CONSENT_COPY.withdrawLabel }),
    );

    const withdrawn = await screen.findByTestId("repeat-consent-withdrawn");
    for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
      expect(
        (withdrawn.textContent ?? "").match(pattern),
        `Banned pattern on the repeat-consent withdrawn notice: ${pattern}`,
      ).toBeNull();
    }
  });
});

describe("repeat consent — not bundled into the approve step", () => {
  beforeEach(() => {
    localStorage.clear();
    resetExecutionCountersForTests();
    push.mockClear();
  });

  it("never appears in the plan review or its approval gate for an eligible workflow", async () => {
    const user = userEvent.setup();

    render(
      <DemoStateProvider>
        <RecommendationReview workflowKey="delete_activity_7b" />
      </DemoStateProvider>,
    );

    expect(screen.queryByTestId("repeat-consent-prompt")).not.toBeInTheDocument();
    expect(
      screen.queryByText(REPEAT_CONSENT_COPY.promptTitle),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Phê duyệt" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent ?? "").not.toContain(
      REPEAT_CONSENT_COPY.promptTitle,
    );
    expect(dialog.textContent ?? "").not.toContain(
      REPEAT_CONSENT_COPY.grantLabel,
    );

    await user.click(within(dialog).getByRole("button", { name: "Phê duyệt" }));

    // Approving starts the work; it never grants a standing permission.
    expect(
      screen.queryByTestId("repeat-consent-prompt"),
    ).not.toBeInTheDocument();
    expect(readPersistedState().repeatConsentGrants ?? {}).toEqual({});
  });
});
