import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RecommendationReview } from "../components/recommendation-review";
import { getWorkflowReviewStages } from "../lib/reviews";
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

async function advanceToApprove(user: ReturnType<typeof userEvent.setup>) {
  const stages = getWorkflowReviewStages(DELETE_ACTIVITY_WORKFLOW_KEY);
  const approve = stages.find((stage) => stage.stage === "approve");
  expect(approve).toBeDefined();

  let guard = 0;
  while (
    screen.getByRole("heading", { level: 3 }).textContent !== approve?.title &&
    guard < 10
  ) {
    await user.click(screen.getByRole("button", { name: "Tiếp theo" }));
    guard += 1;
  }

  expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent(
    approve?.title ?? "",
  );
}

describe("Workflow 7b review → approve → In Progress", () => {
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

  it("completes five-stage review and routes to In Progress on Approve", async () => {
    const user = userEvent.setup();
    const stages = getWorkflowReviewStages(DELETE_ACTIVITY_WORKFLOW_KEY);

    expect(stages).toHaveLength(5);

    render(<RecommendationReview workflowKey={DELETE_ACTIVITY_WORKFLOW_KEY} />);

    await advanceToApprove(user);
    await user.click(screen.getByRole("button", { name: "Phê duyệt" }));

    expect(mockStartExecution).toHaveBeenCalledTimes(1);
    expect(mockStartExecution).toHaveBeenCalledWith(DELETE_ACTIVITY_WORKFLOW_KEY);
    expect(push).toHaveBeenCalledWith(
      "/decisions/in-progress/exec-delete_activity_7b-1",
    );
  });
});
