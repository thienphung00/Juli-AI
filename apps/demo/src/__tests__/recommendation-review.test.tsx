import { render, screen } from "@testing-library/react";
import { useEffect, useState, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RecommendationReview } from "../components/recommendation-review";
import {
  CREATE_HERO_PRODUCT_WORKFLOW_KEY,
  OPTIMIZE_PRODUCT_WORKFLOW_KEY,
} from "../lib/reviews";

const push = vi.fn();
const mockStartExecution = vi.fn(() => "exec-create_hero_product_1-1");

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
  usePathname: vi.fn(() => "/decisions/recommendations/create_hero_product_1"),
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

describe("RecommendationReview routing (plan-review spine only since #910)", () => {
  beforeEach(() => {
    workflowReviewDrafts = {};
    mockStateListeners.clear();
    push.mockClear();
    mockStartExecution.mockClear();
  });

  it("routes migrated workflows to the plan-review spine, not the five-stage review", () => {
    for (const workflowKey of [
      "delete_activity_7b",
      OPTIMIZE_PRODUCT_WORKFLOW_KEY,
      "create_activity_7a",
      "update_activity_7c",
      "process_order_5",
      "prevent_cancellation_8a",
      "prevent_return_8b",
      "prevent_refund_8c",
    ]) {
      const { unmount } = render(
        <RecommendationReview workflowKey={workflowKey} />,
      );

      expect(screen.getByTestId("plan-review-card")).toBeInTheDocument();
      expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Tiếp theo" }),
      ).not.toBeInTheDocument();

      unmount();
    }
  });

  it("routes create_hero_product_1 to the plan-review spine with its uploads reachable (#909)", () => {
    // The eleventh and last migration. Its review route must reach the
    // upload controls — this is the reachability gap that let the original
    // defect ship (uploads green in isolation, count 0 from every route).
    const { container, unmount } = render(
      <RecommendationReview workflowKey={CREATE_HERO_PRODUCT_WORKFLOW_KEY} />,
    );

    expect(screen.getByTestId("plan-review-card")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(container.querySelectorAll('input[type="file"]')).toHaveLength(2);

    unmount();
  });

  it("renders a recoverable not-found state for unsupported workflow keys", () => {
    // Through the public router: unsupported keys (scaffold-only FBT intake
    // keys, malformed URLs) have no plan review, so they render the
    // recoverable not-found state instead of the spine.
    render(<RecommendationReview workflowKey="prevent_return_8b_fbt" />);

    expect(
      screen.getByRole("status", { name: "Không tìm thấy quy trình" }),
    ).toHaveTextContent("Quy trình không được hỗ trợ");
    expect(screen.getByRole("link", { name: "Về Quyết định" })).toHaveAttribute(
      "href",
      "/decisions",
    );
  });
});
