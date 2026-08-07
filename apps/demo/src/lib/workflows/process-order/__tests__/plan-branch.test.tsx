import { render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlanReviewCard } from "../../../../components/plan-review-card";
import {
  PROCESS_ORDER_BRANCHES,
  PROCESS_ORDER_BRANCH_SELLER,
  PROCESS_ORDER_BRANCH_TIKTOK,
  getProcessOrderPlanReview,
} from "../plan";

/**
 * PRD #758 user story 12 — choosing one delivery branch must not leave the
 * other branch's fields on screen. The plan is a pure function of the chosen
 * branch, so this asserts the rendered DOM for each branch and for the switch
 * between them (ADR-055 item 8: "only the chosen branch's fields render").
 */

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
    push,
    refresh: vi.fn(),
    replace: vi.fn(),
  })),
  usePathname: vi.fn(() => "/decisions/recommendations/process-order"),
  useSearchParams: vi.fn(),
}));

vi.mock("../../../../components/demo-state", () => ({
  DemoStateProvider: ({ children }: { children: ReactNode }) => children,
  useDemoState: () => ({
    feedback: null,
    mode: "mock" as const,
    mutableState: {
      rejectedRecommendationIds: [],
      approvedRecommendationIds: [],
      workflowInputs: {},
      workflowReviewDrafts: {},
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
    startExecution: vi.fn((workflowKey: string) => `exec-${workflowKey}-1`),
    updateMutableState: vi.fn(),
  }),
}));

vi.mock("../../../../components/impact-block", () => ({
  IMPACT_UNAVAILABLE_TEXT: "Chưa có số liệu",
  PlanImpactBlock: () => <div data-testid="plan-impact" />,
}));

const TIKTOK_ONLY_VALUES = ["Hóa đơn thương mại", "09:00"];
const SELLER_ONLY_VALUES = ["TK-20260807-001", "SP-TKT-01"];

function renderBranch(branch: (typeof PROCESS_ORDER_BRANCHES)[number]) {
  return render(<PlanReviewCard plan={getProcessOrderPlanReview(branch)} />);
}

function cardText(): string {
  return screen.getByTestId("plan-review-card").textContent ?? "";
}

describe("process_order_5 branch-gated Details on screen", () => {
  beforeEach(() => {
    push.mockClear();
  });

  it("shows only the TikTok-pickup detail when that branch is chosen", () => {
    renderBranch(PROCESS_ORDER_BRANCH_TIKTOK);

    const details = screen.getByTestId("plan-details");
    for (const value of TIKTOK_ONLY_VALUES) {
      expect(details).toHaveTextContent(value);
    }
    // The abandoned branch is not merely collapsed — it is not in the DOM.
    for (const value of SELLER_ONLY_VALUES) {
      expect(cardText()).not.toContain(value);
    }
  });

  it("shows only the seller-delivery detail when that branch is chosen", () => {
    renderBranch(PROCESS_ORDER_BRANCH_SELLER);

    const details = screen.getByTestId("plan-details");
    for (const value of SELLER_ONLY_VALUES) {
      expect(details).toHaveTextContent(value);
    }
    for (const value of TIKTOK_ONLY_VALUES) {
      expect(cardText()).not.toContain(value);
    }
  });

  it("replaces the Details section when the discriminator switches", () => {
    const { unmount } = renderBranch(PROCESS_ORDER_BRANCH_TIKTOK);
    expect(screen.getByTestId("plan-details")).toHaveTextContent(
      "Hóa đơn thương mại",
    );
    unmount();

    renderBranch(PROCESS_ORDER_BRANCH_SELLER);

    const details = screen.getByTestId("plan-details");
    expect(details).toHaveTextContent("TK-20260807-001");
    // Nothing from the abandoned branch survives the switch.
    for (const value of TIKTOK_ONLY_VALUES) {
      expect(cardText()).not.toContain(value);
    }
  });

  it("renders each branch's Details as exactly its own two lines", () => {
    for (const branch of PROCESS_ORDER_BRANCHES) {
      const { unmount } = renderBranch(branch);

      const details = screen.getByTestId("plan-details");
      expect(within(details).getAllByText(/\S/, { selector: "p" })).toHaveLength(
        2,
      );

      unmount();
    }
  });
});
