import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InProgressDetailView } from "../app/decisions/in-progress/[executionId]/page";
import {
  DemoStateProvider,
  useDemoState,
} from "../components/demo-state";
import { getWorkflowTitle } from "../components/in-progress-panel";
import { RecommendationReview } from "../components/recommendation-review";
import { RecommendationsPanel } from "../components/recommendations-panel";
import { sanitizeSellerReviewText } from "../lib/review-seller-copy";
import {
  PREVENT_CANCELLATION_TOOL_NAME,
  PREVENT_CANCELLATION_WORKFLOW_KEY,
  PREVENT_REFUND_TOOL_NAME,
  PREVENT_REFUND_WORKFLOW_KEY,
  PREVENT_RETURN_FBT_INTAKE_KEY,
  PREVENT_RETURN_TOOL_NAME,
  PREVENT_RETURN_WORKFLOW_KEY,
  createPreventCancellationTimeline,
  createPreventRefundTimeline,
  createPreventReturnTimeline,
  resetExecutionCountersForTests,
  startExecution,
} from "../lib/executions";
import { recommendationFixtures } from "../lib/recommendations";
import {
  getWorkflowReviewStages,
  isReviewExecutableWorkflow,
} from "../lib/reviews";
import { confirmApproveThroughGate } from "./review-test-helpers";

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
  usePathname: vi.fn(() => "/decisions"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

const WORKFLOWS = [
  {
    workflowKey: PREVENT_CANCELLATION_WORKFLOW_KEY,
    toolName: PREVENT_CANCELLATION_TOOL_NAME,
    executionId: "exec-prevent_cancellation_8a-1",
    expectedStepCount: 10,
    waitTitle: "Chờ trạng thái huỷ đơn",
    outcomeTitle: "Đã phê duyệt / từ chối / hết hạn / thất bại",
    recoverySnippet: "Làm mới yêu cầu huỷ đơn sau timeout webhook",
  },
  {
    workflowKey: PREVENT_RETURN_WORKFLOW_KEY,
    toolName: PREVENT_RETURN_TOOL_NAME,
    executionId: "exec-prevent_return_8b-1",
    expectedStepCount: 15,
    waitTitle: "Chờ cập nhật trạng thái RMA",
    outcomeTitle: "Đã trả / từ chối / nhập lại kho / thất bại",
    recoverySnippet: "Giữ kết quả kiểm tra khi nhập kho thất bại",
  },
  {
    workflowKey: PREVENT_REFUND_WORKFLOW_KEY,
    toolName: PREVENT_REFUND_TOOL_NAME,
    executionId: "exec-prevent_refund_8c-1",
    expectedStepCount: 10,
    waitTitle: "Chờ hoàn tiền thành công",
    outcomeTitle: "Đã hoàn tiền / từ chối / thất bại",
    recoverySnippet: "Không xác nhận tiền đã chuyển trước khi webhook xác nhận",
  },
] as const;

function ExecutionProbe() {
  const { mutableState } = useDemoState();
  return (
    <output data-testid="execution-probe">
      {JSON.stringify(mutableState)}
    </output>
  );
}

async function advanceToApprove(user: ReturnType<typeof userEvent.setup>) {
  while (!screen.queryByRole("button", { name: "Phê duyệt" })) {
    await user.click(screen.getByRole("button", { name: "Tiếp theo" }));
  }
}

async function runReviewApproveInProgressCase({
  workflowKey,
  toolName,
  executionId,
  expectedStepCount,
  waitTitle,
  outcomeTitle,
  recoverySnippet,
}: (typeof WORKFLOWS)[number]) {
  const user = userEvent.setup();
  const stages = getWorkflowReviewStages(workflowKey);

  expect(stages.map((stage) => stage.stage)).toEqual([
    "why",
    "analytics",
    "inputs",
    "preview",
    "approve",
  ]);

  render(
    <DemoStateProvider>
      <RecommendationReview workflowKey={workflowKey} />
      <ExecutionProbe />
    </DemoStateProvider>,
  );

  expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent(
    stages[0].title,
  );

  await advanceToApprove(user);
  await confirmApproveThroughGate(user);

  expect(push).toHaveBeenCalledWith(`/decisions/in-progress/${executionId}`);

  const state = JSON.parse(
    screen.getByTestId("execution-probe").textContent ?? "{}",
  );
  const record = state.executionRecords[executionId];

  expect(state.approvedRecommendationIds).toContain(workflowKey);
  expect(record.workflowKey).toBe(workflowKey);
  expect(record.toolName).toBe(toolName);
  expect(record.lifecycleStatus).toBe("executing");
  expect(record.timeline).toHaveLength(expectedStepCount);
  expect(record.timeline[0].status).toBe("running");

  cleanup();

  render(
    <DemoStateProvider>
      <InProgressDetailView executionId={executionId} />
    </DemoStateProvider>,
  );

  await waitFor(() => {
    expect(
      screen.getAllByText(getWorkflowTitle(workflowKey)).length,
    ).toBeGreaterThan(0);
  });

  // Seller-facing detail view never shows raw workflow_key/toolName (DUX-8, ADR-035 banned patterns).
  expect(screen.queryByText(workflowKey)).not.toBeInTheDocument();
  expect(screen.queryByText(toolName)).not.toBeInTheDocument();

  // Expand the steps list to verify they exist (issue #762 - steps hidden by default)
  const expandButton = screen.getByRole("button", {
    name: "Xem tất cả các bước",
  });
  await user.click(expandButton);

  await waitFor(() => {
    expect(screen.getAllByRole("listitem")).toHaveLength(expectedStepCount);
  });

  expect(screen.getByText(waitTitle)).toBeInTheDocument();
  expect(screen.getByText(outcomeTitle)).toBeInTheDocument();
  expect(
    screen.getByText(sanitizeSellerReviewText(recoverySnippet), {
      exact: false,
    }),
  ).toBeInTheDocument();
}

describe("Workflows 7–9 review → approve → In Progress", () => {
  beforeEach(() => {
    localStorage.clear();
    resetExecutionCountersForTests();
    push.mockClear();
  });

  afterEach(() => {
    cleanup();
  });

  it("completes prevent_cancellation_8a review and creates the correct mock execution", async () => {
    await runReviewApproveInProgressCase(WORKFLOWS[0]);
  });

  it("completes prevent_return_8b review and creates the correct mock execution", async () => {
    await runReviewApproveInProgressCase(WORKFLOWS[1]);
  });

  it("completes prevent_refund_8c review and creates the correct mock execution", async () => {
    await runReviewApproveInProgressCase(WORKFLOWS[2]);
  });

  it("one integration test per workflow covers review approve In Progress public behavior", () => {
    for (const { workflowKey } of WORKFLOWS) {
      expect(getWorkflowReviewStages(workflowKey)).toHaveLength(5);
    }
  });

  it("keeps prevent-return FBT intake scaffold-only and not executable", () => {
    expect(isReviewExecutableWorkflow(PREVENT_RETURN_FBT_INTAKE_KEY)).toBe(
      false,
    );
    expect(getWorkflowReviewStages(PREVENT_RETURN_FBT_INTAKE_KEY)).toEqual([]);
    expect(() => startExecution(PREVENT_RETURN_FBT_INTAKE_KEY)).toThrow(
      /Unsupported workflow key/,
    );

    const returnFixture = recommendationFixtures.find(
      (fixture) => fixture.workflowKey === PREVENT_RETURN_WORKFLOW_KEY,
    );
    expect(returnFixture?.knownLimits).toMatch(/FBT/);
    expect(returnFixture?.knownLimits).toMatch(/chỉ ghi nhận|chưa hỗ trợ/);

    const returnTimeline = createPreventReturnTimeline();
    expect(
      returnTimeline.some((step) =>
        /FBT|Update Inventory|nhập lại kho/i.test(step.title),
      ),
    ).toBe(true);
    expect(
      returnTimeline.every(
        (step) =>
          !/seller Update Inventory FBT|cập nhật tồn kho FBT/i.test(step.title),
      ),
    ).toBe(true);
  });

  it("enables Approve for workflows 7–9 while keeping Reject on the shared card contract", async () => {
    const user = userEvent.setup();

    render(
      <DemoStateProvider>
        <RecommendationsPanel panelId="recommendations-panel" />
      </DemoStateProvider>,
    );

    for (const { workflowKey } of WORKFLOWS) {
      const card = screen
        .getAllByRole("article")
        .find((node) => node.getAttribute("data-workflow-key") === workflowKey);

      expect(card).toBeTruthy();
      const approveButton = within(card as HTMLElement).getByRole("button", {
        name: "Phê duyệt",
      });
      expect(approveButton).toBeEnabled();
      expect(approveButton).not.toHaveAttribute("aria-describedby");

      await user.click(
        within(card as HTMLElement).getByRole("button", { name: "Từ chối" }),
      );
      expect(
        screen
          .queryAllByRole("article")
          .find((node) => node.getAttribute("data-workflow-key") === workflowKey),
      ).toBeUndefined();
    }
  });
});
