import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RecommendationReview } from "../components/recommendation-review";
import { recommendationFixtures } from "../lib/recommendations";
import {
  PLAN_REASONING_DISCLOSURE_QUESTION,
  type PlanReviewContent,
} from "../lib/plan-reviews";
import {
  PLAN_CAVEAT_CLASSES,
  getPlanCaveats,
  selectPlanCaveats,
} from "../lib/plan-caveats";
import {
  REVIEW_UI_BANNED_PATTERNS,
  sanitizeSellerReviewText,
} from "../lib/review-seller-copy";
import { getCreateActivityPlanReview } from "../lib/workflows/create-activity/plan";
import { CREATE_ACTIVITY_WORKFLOW_KEY } from "../lib/workflows/create-activity";
import { getCreateHeroProductPlanReview } from "../lib/workflows/create-hero-product/plan";
import { CREATE_HERO_PRODUCT_WORKFLOW_KEY } from "../lib/workflows/create-hero-product";
import { getDeleteActivityPlanReview } from "../lib/workflows/delete-activity/plan";
import { DELETE_ACTIVITY_WORKFLOW_KEY } from "../lib/workflows/delete-activity";
import { getOptimizeProductPlanReview } from "../lib/workflows/optimize-product/plan";
import { OPTIMIZE_PRODUCT_WORKFLOW_KEY } from "../lib/workflows/optimize-product";
import { getProcessOrderPlanReview } from "../lib/workflows/process-order/plan";
import { PROCESS_ORDER_WORKFLOW_KEY } from "../lib/workflows/process-order";
import { getUpdateActivityPlanReview } from "../lib/workflows/update-activity/plan";
import { UPDATE_ACTIVITY_WORKFLOW_KEY } from "../lib/workflows/update-activity";
import { getReplenishInventoryPlanReview } from "../lib/workflows/replenish-inventory/plan";
import { REPLENISH_INVENTORY_WORKFLOW_KEY } from "../lib/workflows/replenish-inventory";
import { getClearExcessPlanReview } from "../lib/workflows/clear-excess/plan";
import { CLEAR_EXCESS_WORKFLOW_KEY } from "../lib/workflows/clear-excess";
import { getPreventCancellationPlanReview } from "../lib/workflows/prevent-cancellation/plan";
import { PREVENT_CANCELLATION_WORKFLOW_KEY } from "../lib/workflows/prevent-cancellation";
import { getPreventReturnPlanReview } from "../lib/workflows/prevent-return/plan";
import { PREVENT_RETURN_WORKFLOW_KEY } from "../lib/workflows/prevent-return";
import { getPreventRefundPlanReview } from "../lib/workflows/prevent-refund/plan";
import { PREVENT_REFUND_WORKFLOW_KEY } from "../lib/workflows/prevent-refund";
import {
  confirmApproveThroughGate,
  makeValidPngFile,
  selectUploadFile,
} from "./review-test-helpers";

/**
 * Shared Situation → Decision → Details spine assertions (ADR-055 items 1, 8,
 * 13–14). Every workflow migrated onto the plan-review spine registers one
 * entry here and inherits the full assertion set. Workflow-specific content
 * checks live next to each plan module in `lib/workflows/<name>/__tests__/`.
 */
interface SpineTableEntry {
  workflowKey: string;
  getPlan: () => PlanReviewContent;
  /**
   * ADR-055 item 12 — the stated exception to one-tap approval. True only
   * for a plan carrying a "needs you" upload section, whose required upload
   * keeps Phê duyệt disabled until the seller supplies a file. Entries
   * without this flag keep the unqualified one-tap contract.
   */
  sellerUploadGate?: true;
}

const SPINE_WORKFLOWS: SpineTableEntry[] = [
  {
    workflowKey: DELETE_ACTIVITY_WORKFLOW_KEY,
    getPlan: getDeleteActivityPlanReview,
  },
  {
    workflowKey: OPTIMIZE_PRODUCT_WORKFLOW_KEY,
    getPlan: getOptimizeProductPlanReview,
  },
  {
    workflowKey: CREATE_ACTIVITY_WORKFLOW_KEY,
    getPlan: getCreateActivityPlanReview,
  },
  {
    workflowKey: UPDATE_ACTIVITY_WORKFLOW_KEY,
    getPlan: getUpdateActivityPlanReview,
  },
  {
    workflowKey: REPLENISH_INVENTORY_WORKFLOW_KEY,
    getPlan: getReplenishInventoryPlanReview,
  },
  {
    workflowKey: CLEAR_EXCESS_WORKFLOW_KEY,
    getPlan: getClearExcessPlanReview,
  },
  {
    workflowKey: PROCESS_ORDER_WORKFLOW_KEY,
    getPlan: getProcessOrderPlanReview,
  },
  {
    workflowKey: PREVENT_CANCELLATION_WORKFLOW_KEY,
    getPlan: getPreventCancellationPlanReview,
  },
  {
    workflowKey: PREVENT_RETURN_WORKFLOW_KEY,
    getPlan: getPreventReturnPlanReview,
  },
  {
    workflowKey: PREVENT_REFUND_WORKFLOW_KEY,
    getPlan: getPreventRefundPlanReview,
  },
  {
    workflowKey: CREATE_HERO_PRODUCT_WORKFLOW_KEY,
    getPlan: getCreateHeroProductPlanReview,
    sellerUploadGate: true,
  },
];

const push = vi.fn();
const mockStartExecution = vi.fn(
  (workflowKey: string) => `exec-${workflowKey}-1`,
);

let workflowReviewDrafts: Record<string, Record<string, string>> = {};

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
    push,
    refresh: vi.fn(),
    replace: vi.fn(),
  })),
  usePathname: vi.fn(() => "/decisions/recommendations/spine"),
  useSearchParams: vi.fn(),
}));

const mockStateListeners = new Set<() => void>();

function notifyMockStateListeners() {
  mockStateListeners.forEach((listener) => listener());
}

vi.mock("../components/demo-state", () => ({
  DemoStateProvider: ({ children }: { children: ReactNode }) => children,
  useDemoState: () => {
    const [, setTick] = useState(0);

    useEffect(() => {
      const listener = () => setTick((tick) => tick + 1);
      mockStateListeners.add(listener);
      return () => {
        mockStateListeners.delete(listener);
      };
    }, []);

    return {
      feedback: null,
      mode: "mock" as const,
      mutableState: {
        rejectedRecommendationIds: [],
        approvedRecommendationIds: [],
        workflowInputs: {},
        workflowReviewDrafts,
        executionRecords: {},
        executionProgress: {},
        decisionsView: "recommendations" as const,
        analyticsMetric: "net-revenue",
        analyticsRange: "30d" as const,
        settingsDraft: {},
      },
      recommendationContext: null,
      requestSignIn: vi.fn(),
      resetMockState: vi.fn(),
      setRecommendationContext: vi.fn(),
      startExecution: mockStartExecution,
      updateMutableState: (
        updater:
          | ((current: {
              workflowReviewDrafts: Record<string, Record<string, string>>;
            }) => {
              workflowReviewDrafts: Record<string, Record<string, string>>;
            })
          | {
              workflowReviewDrafts: Record<string, Record<string, string>>;
            },
      ) => {
        const current = { workflowReviewDrafts };
        const resolved =
          typeof updater === "function" ? updater(current) : updater;
        workflowReviewDrafts = resolved.workflowReviewDrafts;
        notifyMockStateListeners();
      },
    };
  },
}));

describe.each(SPINE_WORKFLOWS)(
  "Plan review spine — $workflowKey",
  ({ workflowKey, getPlan, sellerUploadGate }) => {
    const plan = getPlan();
    const fixture = recommendationFixtures.find(
      (entry) => entry.workflowKey === workflowKey,
    );
    const recommendedOptions = plan.decision.recommendedOptions;
    // Summary row + reasoning disclosure + Phê duyệt, plus the recommended
    // options disclosure where the workflow carries one. The reasoning
    // disclosure is unconditional — every plan has reasoning (ADR-055 item 11).
    const restingButtonCount = 3 + (recommendedOptions ? 1 : 0);

    function renderSpine() {
      return render(<RecommendationReview workflowKey={workflowKey} />);
    }

    function getReasoningRow() {
      return screen.getByRole("button", {
        name: new RegExp(
          PLAN_REASONING_DISCLOSURE_QUESTION.replace("?", "\\?"),
        ),
      });
    }

    function revealedReasoning() {
      return sanitizeSellerReviewText(plan.decision.reasoning);
    }

    function getSituationRow() {
      return screen.getByRole("button", {
        name: new RegExp(
          plan.situation.disclosureQuestion.replace("?", "\\?"),
        ),
      });
    }

    beforeEach(() => {
      workflowReviewDrafts = {};
      mockStateListeners.clear();
      push.mockClear();
      mockStartExecution.mockClear();
      vi.mocked(useRouter).mockReturnValue({
        back: vi.fn(),
        forward: vi.fn(),
        prefetch: vi.fn(),
        push,
        refresh: vi.fn(),
        replace: vi.fn(),
      });
    });

    it("routes to the plan-review spine, not the five-stage review", () => {
      renderSpine();

      expect(screen.getByTestId("plan-review-card")).toBeInTheDocument();
      expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Tiếp theo" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Quay lại" }),
      ).not.toBeInTheDocument();
    });

    it("rests on title, one-sentence proposal, summary row, and one primary action — no form fields", () => {
      renderSpine();

      const card = screen.getByTestId("plan-review-card");

      expect(within(card).getByRole("heading")).toHaveTextContent(plan.title);
      expect(
        within(card).getByText(plan.decision.proposal),
      ).toBeInTheDocument();

      const summaryRow = getSituationRow();
      expect(summaryRow).toHaveAttribute("aria-expanded", "false");
      expect(summaryRow).toHaveTextContent(plan.situation.summary);

      expect(
        within(card).getByRole("button", { name: "Phê duyệt" }),
      ).toBeInTheDocument();
      expect(within(card).getAllByRole("button")).toHaveLength(
        restingButtonCount,
      );

      // Summarise, never enumerate: no labelled form fields at rest.
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    });

    it("collapses the known fields into one summary row with a count", () => {
      renderSpine();

      expect(getSituationRow()).toHaveTextContent(
        `${plan.situation.detailLines.length} thông tin`,
      );
    });

    it("keeps the summary visible on expansion and resolves the Analytics deep link", async () => {
      const user = userEvent.setup();

      renderSpine();

      const summaryRow = getSituationRow();
      await user.click(summaryRow);

      expect(summaryRow).toHaveAttribute("aria-expanded", "true");
      expect(summaryRow).toHaveTextContent(plan.situation.summary);
      for (const line of plan.situation.detailLines) {
        expect(screen.getByText(line)).toBeInTheDocument();
      }
      expect(
        screen.getByRole("link", { name: "Xem trên Phân tích" }),
      ).toHaveAttribute("href", plan.situation.analyticsMetricHref);

      await user.click(summaryRow);
      expect(summaryRow).toHaveAttribute("aria-expanded", "false");
      for (const line of plan.situation.detailLines) {
        expect(screen.queryByText(line)).not.toBeInTheDocument();
      }
    });

    it("phrases every disclosure as a question, not a noun", () => {
      renderSpine();

      expect(plan.situation.disclosureQuestion.trim().endsWith("?")).toBe(true);
      expect(getSituationRow()).toHaveTextContent(/\?/);
      expect(getSituationRow()).not.toHaveTextContent(/Chi tiết/);

      expect(PLAN_REASONING_DISCLOSURE_QUESTION.trim().endsWith("?")).toBe(
        true,
      );
      expect(getReasoningRow()).toHaveTextContent(/\?/);

      if (recommendedOptions) {
        expect(
          recommendedOptions.disclosureQuestion.trim().endsWith("?"),
        ).toBe(true);
      }
    });

    // Reasoning disclosure (ADR-055 items 3, 11). The ask affordance lives
    // inside the section it explains — the Decision body — and is never empty:
    // `reasoning` is required on every plan, so no workflow can ship an
    // expansion that opens onto nothing.
    it("carries a non-empty reasoning behind the disclosure", () => {
      expect(plan.decision.reasoning.trim().length).toBeGreaterThan(0);
      expect(revealedReasoning().trim().length).toBeGreaterThan(0);
    });

    it("rests with the reasoning disclosure closed, inside the Decision section", () => {
      renderSpine();

      const decision = screen.getByTestId("plan-decision");
      const reasoningRow = within(decision).getByRole("button", {
        name: new RegExp(
          PLAN_REASONING_DISCLOSURE_QUESTION.replace("?", "\\?"),
        ),
      });

      expect(reasoningRow).toHaveAttribute("aria-expanded", "false");
      expect(screen.queryByTestId("plan-reasoning")).not.toBeInTheDocument();
      expect(screen.queryByText(revealedReasoning())).not.toBeInTheDocument();
    });

    it("adds the reasoning on expansion without replacing the proposal, and no free-text box", async () => {
      const user = userEvent.setup();

      renderSpine();

      const reasoningRow = getReasoningRow();
      await user.click(reasoningRow);

      expect(reasoningRow).toHaveAttribute("aria-expanded", "true");
      expect(screen.getByTestId("plan-reasoning")).toHaveTextContent(
        revealedReasoning(),
      );
      // Expansion adds; it never replaces what was resting.
      expect(screen.getByText(plan.decision.proposal)).toBeInTheDocument();

      // Pre-authored copy, not a conversation: nothing to type into.
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    });

    it("returns to the resting card when the reasoning disclosure closes", async () => {
      const user = userEvent.setup();

      renderSpine();

      const card = screen.getByTestId("plan-review-card");
      const reasoningRow = getReasoningRow();

      await user.click(reasoningRow);
      await user.click(reasoningRow);

      expect(reasoningRow).toHaveAttribute("aria-expanded", "false");
      expect(screen.queryByTestId("plan-reasoning")).not.toBeInTheDocument();
      expect(screen.queryByText(revealedReasoning())).not.toBeInTheDocument();
      expect(within(card).getAllByRole("button")).toHaveLength(
        restingButtonCount,
      );
    });

    if (plan.details) {
      it("renders the branch-gated detail lines", () => {
        renderSpine();

        const details = screen.getByTestId("plan-details");
        for (const line of plan.details?.detailLines ?? []) {
          expect(details).toHaveTextContent(line);
        }
      });
    } else {
      it("renders the Details section as absent — no stub, no empty state", () => {
        renderSpine();

        expect(screen.queryByTestId("plan-details")).not.toBeInTheDocument();

        const card = screen.getByTestId("plan-review-card");
        for (const button of within(card).getAllByRole("button")) {
          if (sellerUploadGate && button.textContent === "Phê duyệt") {
            // The upload gate deliberately rests the primary action disabled
            // (ADR-055 item 12) — asserted in the gate-specific tests below.
            continue;
          }
          expect(button).not.toBeDisabled();
        }
      });
    }

    if (recommendedOptions) {
      it("reveals the recommended options on expansion, marking the proposed value", async () => {
        const user = userEvent.setup();

        renderSpine();

        // At rest only the proposal shows — alternatives wait behind the
        // question-phrased disclosure.
        expect(
          screen.queryByTestId("plan-decision-options"),
        ).not.toBeInTheDocument();

        const optionsRow = screen.getByRole("button", {
          name: new RegExp(
            recommendedOptions.disclosureQuestion.replace("?", "\\?"),
          ),
        });
        expect(optionsRow).toHaveAttribute("aria-expanded", "false");

        await user.click(optionsRow);

        const optionsRegion = screen.getByTestId("plan-decision-options");
        for (const group of recommendedOptions.groups) {
          expect(optionsRegion).toHaveTextContent(group.label);
          for (const option of group.options) {
            expect(optionsRegion).toHaveTextContent(option.value);
          }
        }

        // One proposed value marked per group — read-only, no editing
        // affordance (ADR-055 item 14).
        expect(
          within(optionsRegion).getAllByText("Gợi ý bởi Juli"),
        ).toHaveLength(recommendedOptions.groups.length);
        expect(
          within(optionsRegion).queryByRole("textbox"),
        ).not.toBeInTheDocument();
        expect(
          within(optionsRegion).queryByRole("combobox"),
        ).not.toBeInTheDocument();
      });
    }

    if (!sellerUploadGate) {
      it("approves in one tap without expanding anything and routes to In Progress", async () => {
        const user = userEvent.setup();

        renderSpine();

        await confirmApproveThroughGate(user);

        expect(mockStartExecution).toHaveBeenCalledTimes(1);
        expect(mockStartExecution).toHaveBeenCalledWith(workflowKey);
        expect(push).toHaveBeenCalledWith(
          `/decisions/in-progress/exec-${workflowKey}-1`,
        );
      });

      it("opens the approval gate before starting execution", async () => {
        const user = userEvent.setup();

        renderSpine();

        await user.click(screen.getByRole("button", { name: "Phê duyệt" }));

        expect(screen.getByRole("dialog")).toBeInTheDocument();
        expect(mockStartExecution).not.toHaveBeenCalled();
      });
    } else {
      // ADR-055 item 12 — the stated exception to one-tap approval: the
      // required upload keeps Phê duyệt disabled, so nothing can fire
      // startExecution until the seller supplies a file.
      it("blocks approval while the required upload is missing", async () => {
        const user = userEvent.setup();

        renderSpine();

        const approveButton = screen.getByRole("button", {
          name: "Phê duyệt",
        });
        expect(approveButton).toBeDisabled();

        await user.click(approveButton);

        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
        expect(mockStartExecution).not.toHaveBeenCalled();
      });

      it("opens the approval gate before starting execution once the required upload is supplied", async () => {
        const user = userEvent.setup();

        renderSpine();

        selectUploadFile(
          screen.getByLabelText(/Ảnh sản phẩm/),
          makeValidPngFile(),
        );
        await waitFor(() => {
          expect(
            screen.getByRole("button", { name: "Phê duyệt" }),
          ).toBeEnabled();
        });

        await user.click(screen.getByRole("button", { name: "Phê duyệt" }));

        expect(screen.getByRole("dialog")).toBeInTheDocument();
        expect(mockStartExecution).not.toHaveBeenCalled();
      });

      it("approves and routes to In Progress after the required upload is supplied", async () => {
        const user = userEvent.setup();

        renderSpine();

        selectUploadFile(
          screen.getByLabelText(/Ảnh sản phẩm/),
          makeValidPngFile(),
        );
        await waitFor(() => {
          expect(
            screen.getByRole("button", { name: "Phê duyệt" }),
          ).toBeEnabled();
        });

        await confirmApproveThroughGate(user);

        expect(mockStartExecution).toHaveBeenCalledTimes(1);
        expect(mockStartExecution).toHaveBeenCalledWith(workflowKey);
        expect(push).toHaveBeenCalledWith(
          `/decisions/in-progress/exec-${workflowKey}-1`,
        );
      });
    }

    it("never renders the risks copy, resting or fully expanded", async () => {
      const user = userEvent.setup();

      renderSpine();

      expect(fixture?.risks).toBeTruthy();
      expect(screen.queryByText(fixture!.risks)).not.toBeInTheDocument();

      await user.click(getSituationRow());
      await user.click(getReasoningRow());
      if (recommendedOptions) {
        await user.click(
          screen.getByRole("button", {
            name: new RegExp(
              recommendedOptions.disclosureQuestion.replace("?", "\\?"),
            ),
          }),
        );
      }

      expect(screen.queryByText(fixture!.risks)).not.toBeInTheDocument();
    });

    it("renders no system vocabulary, resting or fully expanded", async () => {
      const user = userEvent.setup();

      renderSpine();

      const card = screen.getByTestId("plan-review-card");

      for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
        expect(card.textContent ?? "").not.toMatch(pattern);
      }

      await user.click(getSituationRow());
      await user.click(getReasoningRow());
      if (recommendedOptions) {
        await user.click(
          screen.getByRole("button", {
            name: new RegExp(
              recommendedOptions.disclosureQuestion.replace("?", "\\?"),
            ),
          }),
        );
      }

      for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
        expect(card.textContent ?? "").not.toMatch(pattern);
      }
    });

    it("links back to the decisions list with highlight query", () => {
      renderSpine();

      expect(
        screen.getByRole("link", { name: "Về danh sách đề xuất" }),
      ).toHaveAttribute("href", `/decisions?highlight=${workflowKey}`);
    });

    // Typed caveat classes (ADR-055 item 10). Every plan carries its caveats
    // typed, so the card applies a per-class rule instead of judging strings.
    const caveats = plan.decision.caveats;
    const hiddenCaveats = [
      ...selectPlanCaveats(caveats, "threshold-undefined"),
      ...selectPlanCaveats(caveats, "fulfilment-unsupported"),
    ];
    const gapCaveats = selectPlanCaveats(caveats, "feature-unavailable");
    const trustCaveats = selectPlanCaveats(caveats, "reassurance");

    it("carries its caveats typed, never as a concatenated blob", () => {
      // Sourced from the shared classification, not parsed out of the string.
      expect(caveats).toEqual(getPlanCaveats(workflowKey));
      expect(caveats.length).toBeGreaterThan(0);
      for (const caveat of caveats) {
        expect(caveat.text.trim().length).toBeGreaterThan(0);
        expect(PLAN_CAVEAT_CLASSES).toContain(caveat.caveatClass);
      }
      // Every workflow carries the undefined-threshold caveat, which is why it
      // discriminates nothing and is hidden.
      expect(
        selectPlanCaveats(caveats, "threshold-undefined").length,
      ).toBeGreaterThan(0);
    });

    it("never renders the concatenated known-limits blob", async () => {
      const user = userEvent.setup();

      renderSpine();

      expect(fixture?.knownLimits).toBeTruthy();
      expect(screen.queryByText(fixture!.knownLimits)).not.toBeInTheDocument();

      await user.click(getSituationRow());
      await user.click(getReasoningRow());

      expect(screen.queryByText(fixture!.knownLimits)).not.toBeInTheDocument();
    });

    it("renders the hidden caveat classes nowhere, resting or fully expanded", async () => {
      const user = userEvent.setup();

      renderSpine();

      const card = screen.getByTestId("plan-review-card");
      for (const caveat of hiddenCaveats) {
        expect(card.textContent ?? "").not.toContain(caveat.text);
      }

      await user.click(getSituationRow());
      await user.click(getReasoningRow());
      if (recommendedOptions) {
        await user.click(
          screen.getByRole("button", {
            name: new RegExp(
              recommendedOptions.disclosureQuestion.replace("?", "\\?"),
            ),
          }),
        );
      }

      for (const caveat of hiddenCaveats) {
        expect(card.textContent ?? "").not.toContain(caveat.text);
      }
    });

    if (gapCaveats.length > 0) {
      it("answers with its functional gaps inside the reasoning expansion", async () => {
        const user = userEvent.setup();

        renderSpine();

        for (const caveat of gapCaveats) {
          expect(
            screen.queryByText(sanitizeSellerReviewText(caveat.text)),
          ).not.toBeInTheDocument();
        }

        await user.click(getReasoningRow());

        const reasoning = screen.getByTestId("plan-reasoning");
        for (const caveat of gapCaveats) {
          expect(reasoning).toHaveTextContent(
            sanitizeSellerReviewText(caveat.text),
          );
        }
      });
    } else {
      it("opens the reasoning expansion onto reasoning alone", async () => {
        const user = userEvent.setup();

        renderSpine();
        await user.click(getReasoningRow());

        expect(
          screen.queryByTestId("plan-reasoning-caveats"),
        ).not.toBeInTheDocument();
      });
    }

    if (trustCaveats.length > 0) {
      it("rests its no-act promises as trust lines in the Decision section", () => {
        renderSpine();

        const trustLines = within(
          screen.getByTestId("plan-decision"),
        ).getByTestId("plan-trust-lines");

        for (const caveat of trustCaveats) {
          expect(trustLines).toHaveTextContent(
            sanitizeSellerReviewText(caveat.text),
          );
        }
      });
    } else {
      it("renders no trust-line block when it makes no no-act promise", () => {
        renderSpine();

        expect(screen.queryByTestId("plan-trust-lines")).not.toBeInTheDocument();
      });
    }
  },
);
