import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RecommendationReview } from "../components/recommendation-review";
import { recommendationFixtures } from "../lib/recommendations";
import type { PlanReviewContent } from "../lib/plan-reviews";
import { REVIEW_UI_BANNED_PATTERNS } from "../lib/review-seller-copy";
import { getDeleteActivityPlanReview } from "../lib/workflows/delete-activity/plan";
import { DELETE_ACTIVITY_WORKFLOW_KEY } from "../lib/workflows/delete-activity";
import { getOptimizeProductPlanReview } from "../lib/workflows/optimize-product/plan";
import { OPTIMIZE_PRODUCT_WORKFLOW_KEY } from "../lib/workflows/optimize-product";
import { confirmApproveThroughGate } from "./review-test-helpers";

/**
 * Shared Situation → Decision → Details spine assertions (ADR-055 items 1, 8,
 * 13–14). Every workflow migrated onto the plan-review spine registers one
 * entry here and inherits the full assertion set. Workflow-specific content
 * checks live next to each plan module in `lib/workflows/<name>/__tests__/`.
 */
interface SpineTableEntry {
  workflowKey: string;
  getPlan: () => PlanReviewContent;
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
  ({ workflowKey, getPlan }) => {
    const plan = getPlan();
    const fixture = recommendationFixtures.find(
      (entry) => entry.workflowKey === workflowKey,
    );
    const recommendedOptions = plan.decision.recommendedOptions;
    const restingButtonCount = 2 + (recommendedOptions ? 1 : 0);

    function renderSpine() {
      return render(<RecommendationReview workflowKey={workflowKey} />);
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

      if (recommendedOptions) {
        expect(
          recommendedOptions.disclosureQuestion.trim().endsWith("?"),
        ).toBe(true);
      }
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

    it("never renders the risks copy, resting or fully expanded", async () => {
      const user = userEvent.setup();

      renderSpine();

      expect(fixture?.risks).toBeTruthy();
      expect(screen.queryByText(fixture!.risks)).not.toBeInTheDocument();

      await user.click(getSituationRow());
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
  },
);
