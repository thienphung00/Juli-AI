import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RecommendationReview } from "../components/recommendation-review";
import { PLAN_REASONING_DISCLOSURE_QUESTION } from "../lib/plan-reviews";
import { recommendationFixtures } from "../lib/recommendations";
import {
  REVIEW_UI_BANNED_PATTERNS,
  SELLER_APPROVE_GATE,
} from "../lib/review-seller-copy";
import { getDeleteActivityPlanReview } from "../lib/workflows/delete-activity/plan";
import { confirmApproveThroughGate } from "./review-test-helpers";
import { DELETE_ACTIVITY_WORKFLOW_KEY } from "../lib/workflows/delete-activity";

const push = vi.fn();
const mockStartExecution = vi.fn(
  () => "exec-delete_activity_7b-1",
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
  usePathname: vi.fn(() => "/decisions/recommendations/delete_activity_7b"),
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

const fixture = recommendationFixtures.find(
  (entry) => entry.workflowKey === DELETE_ACTIVITY_WORKFLOW_KEY,
);

function renderSpine() {
  return render(
    <RecommendationReview workflowKey={DELETE_ACTIVITY_WORKFLOW_KEY} />,
  );
}

describe("Workflow 7b plan review — Situation → Decision → Details spine", () => {
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

  it("resting card shows title, proposal, situation summary row, and one primary action — nothing more", () => {
    const plan = getDeleteActivityPlanReview();

    renderSpine();

    const card = screen.getByTestId("plan-review-card");

    // Title, one-sentence proposal, situation summary row.
    expect(within(card).getByRole("heading")).toHaveTextContent(plan.title);
    expect(within(card).getByText(plan.decision.proposal)).toBeInTheDocument();

    const summaryRow = within(card).getByRole("button", {
      name: new RegExp(plan.situation.disclosureQuestion.replace("?", "\\?")),
    });
    expect(summaryRow).toHaveAttribute("aria-expanded", "false");
    expect(summaryRow).toHaveTextContent(plan.situation.summary);

    // Exactly one primary action, and exactly three buttons total
    // (summary-row disclosure + reasoning disclosure + Phê duyệt).
    expect(
      within(card).getByRole("button", { name: "Phê duyệt" }),
    ).toBeInTheDocument();
    expect(within(card).getAllByRole("button")).toHaveLength(3);

    // No five-stage chrome: no progress tablist, no stage navigation.
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Tiếp theo" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Quay lại" }),
    ).not.toBeInTheDocument();

    // No labelled read-only form fields in the resting card.
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("renders the Details section as absent — no stub, no empty state, no disabled expander", () => {
    renderSpine();

    expect(screen.queryByTestId("plan-details")).not.toBeInTheDocument();

    const card = screen.getByTestId("plan-review-card");
    for (const button of within(card).getAllByRole("button")) {
      expect(button).not.toBeDisabled();
    }
  });

  it("keeps the summary line visible when the situation row expands", async () => {
    const user = userEvent.setup();
    const plan = getDeleteActivityPlanReview();

    renderSpine();

    const summaryRow = screen.getByRole("button", {
      name: new RegExp(plan.situation.disclosureQuestion.replace("?", "\\?")),
    });

    await user.click(summaryRow);

    // Expansion adds detail below and never replaces the summary line.
    expect(summaryRow).toHaveAttribute("aria-expanded", "true");
    expect(summaryRow).toHaveTextContent(plan.situation.summary);
    for (const line of plan.situation.detailLines) {
      expect(screen.getByText(line)).toBeInTheDocument();
    }
    expect(
      screen.getByRole("link", { name: "Xem trên Phân tích" }),
    ).toHaveAttribute("href", plan.situation.analyticsMetricHref);

    // Collapse removes the detail again, still keeping the summary.
    await user.click(summaryRow);
    expect(summaryRow).toHaveAttribute("aria-expanded", "false");
    expect(summaryRow).toHaveTextContent(plan.situation.summary);
    for (const line of plan.situation.detailLines) {
      expect(screen.queryByText(line)).not.toBeInTheDocument();
    }
  });

  it("phrases the disclosure control as a question, not a noun", () => {
    const plan = getDeleteActivityPlanReview();

    renderSpine();

    const summaryRow = screen.getByRole("button", {
      name: new RegExp(plan.situation.disclosureQuestion.replace("?", "\\?")),
    });
    expect(summaryRow).toHaveTextContent(/\?/);
    expect(summaryRow).not.toHaveTextContent(/Chi tiết/);
  });

  it("approves in one tap without expanding anything and routes to In Progress", async () => {
    const user = userEvent.setup();

    renderSpine();

    // No expansion first — straight to the primary action.
    await confirmApproveThroughGate(user);

    expect(mockStartExecution).toHaveBeenCalledTimes(1);
    expect(mockStartExecution).toHaveBeenCalledWith(
      DELETE_ACTIVITY_WORKFLOW_KEY,
    );
    expect(push).toHaveBeenCalledWith(
      "/decisions/in-progress/exec-delete_activity_7b-1",
    );
  });

  it("opens the approval gate before starting execution", async () => {
    const user = userEvent.setup();

    renderSpine();

    await user.click(screen.getByRole("button", { name: "Phê duyệt" }));

    expect(screen.getByRole("dialog")).toHaveTextContent(
      SELLER_APPROVE_GATE.description,
    );
    expect(mockStartExecution).not.toHaveBeenCalled();
  });

  it("never renders the risks copy, resting or expanded", async () => {
    const user = userEvent.setup();
    const plan = getDeleteActivityPlanReview();

    renderSpine();

    expect(fixture?.risks).toBeTruthy();
    expect(screen.queryByText(fixture!.risks)).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", {
        name: new RegExp(plan.situation.disclosureQuestion.replace("?", "\\?")),
      }),
    );
    await user.click(
      screen.getByRole("button", { name: PLAN_REASONING_DISCLOSURE_QUESTION }),
    );

    expect(screen.queryByText(fixture!.risks)).not.toBeInTheDocument();
  });

  it("renders no system vocabulary, resting or expanded", async () => {
    const user = userEvent.setup();
    const plan = getDeleteActivityPlanReview();

    renderSpine();

    const card = screen.getByTestId("plan-review-card");

    for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
      expect(card.textContent ?? "").not.toMatch(pattern);
    }

    await user.click(
      screen.getByRole("button", {
        name: new RegExp(plan.situation.disclosureQuestion.replace("?", "\\?")),
      }),
    );
    await user.click(
      screen.getByRole("button", { name: PLAN_REASONING_DISCLOSURE_QUESTION }),
    );

    for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
      expect(card.textContent ?? "").not.toMatch(pattern);
    }
  });

  it("links back to the decisions list with highlight query", () => {
    renderSpine();

    expect(
      screen.getByRole("link", { name: "Về danh sách đề xuất" }),
    ).toHaveAttribute(
      "href",
      `/decisions?highlight=${DELETE_ACTIVITY_WORKFLOW_KEY}`,
    );
  });
});
