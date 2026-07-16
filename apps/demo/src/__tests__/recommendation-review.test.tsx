import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RecommendationReview } from "../components/recommendation-review";
import {
  CREATE_HERO_PRODUCT_WORKFLOW_KEY,
  getWorkflowReviewStages,
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

function renderReview(workflowKey = CREATE_HERO_PRODUCT_WORKFLOW_KEY) {
  return render(<RecommendationReview workflowKey={workflowKey} />);
}

async function advanceToStage(
  user: ReturnType<typeof userEvent.setup>,
  targetTitle: string,
) {
  const stages = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY);
  const targetIndex = stages.findIndex((stage) => stage.title === targetTitle);
  expect(targetIndex).toBeGreaterThanOrEqual(0);

  let currentTitle = screen.getByRole("heading", { level: 3 }).textContent;
  let guard = 0;

  while (currentTitle !== targetTitle && guard < 10) {
    await user.click(screen.getByRole("button", { name: "Tiếp theo" }));
    currentTitle = screen.getByRole("heading", { level: 3 }).textContent;
    guard += 1;
  }

  expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent(
    targetTitle,
  );
}

describe("RecommendationReview", () => {
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

  it("renders all five stages in order via Next navigation", async () => {
    const user = userEvent.setup();
    const stages = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY);

    renderReview();

    for (const [index, stage] of stages.entries()) {
      expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent(
        stage.title,
      );

      if (index < stages.length - 1) {
        await user.click(screen.getByRole("button", { name: "Tiếp theo" }));
      }
    }
  });

  it("renders Why-stage body as readable paragraphs", () => {
    const why = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY)[0];

    renderReview();

    const stageBody = screen.getByTestId("review-stage-body");
    const paragraphs = within(stageBody).getAllByRole("paragraph");

    expect(paragraphs.length).toBeGreaterThan(1);
    why.body.split("\n\n").forEach((chunk) => {
      expect(stageBody).toHaveTextContent(chunk);
    });
  });

  it("renders Preview-stage tool summary and draft values", async () => {
    const user = userEvent.setup();
    const preview = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY).find(
      (stage) => stage.stage === "preview",
    );

    renderReview();
    await advanceToStage(user, preview?.title ?? "");

    const stageBody = screen.getByTestId("review-stage-body");
    preview?.body.split("\n\n").forEach((chunk) => {
      expect(stageBody).toHaveTextContent(chunk);
    });
    expect(screen.getByTestId("review-draft-summary")).toBeInTheDocument();
  });

  it("renders Approve-stage confirmation copy", async () => {
    const user = userEvent.setup();
    const approve = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY).find(
      (stage) => stage.stage === "approve",
    );

    renderReview();
    await advanceToStage(user, approve?.title ?? "");

    expect(screen.getByTestId("review-stage-body")).toHaveTextContent(
      approve?.body ?? "",
    );
    expect(
      screen.getByRole("button", { name: "Phê duyệt" }),
    ).toBeInTheDocument();
  });

  it("persists Inputs-stage edits across stage navigation", async () => {
    const user = userEvent.setup();
    const inputs = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY).find(
      (stage) => stage.stage === "inputs",
    );

    renderReview();
    await advanceToStage(user, inputs?.title ?? "");

    const brandInput = screen.getByRole("textbox", {
      name: /Nhãn hiệu/,
    });
    await user.clear(brandInput);
    await user.type(brandInput, "BR-9999 — Thương hiệu thử");

    await user.click(screen.getByRole("button", { name: "Tiếp theo" }));
    await user.click(screen.getByRole("button", { name: "Quay lại" }));

    expect(screen.getByRole("textbox", { name: /Nhãn hiệu/ })).toHaveValue(
      "BR-9999 — Thương hiệu thử",
    );
  });

  it("does not call startExecution on mount or before Approve is clicked", async () => {
    const user = userEvent.setup();

    renderReview();
    expect(mockStartExecution).not.toHaveBeenCalled();

    const stages = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY);
    for (let index = 0; index < stages.length - 1; index += 1) {
      await user.click(screen.getByRole("button", { name: "Tiếp theo" }));
      expect(mockStartExecution).not.toHaveBeenCalled();
    }

    expect(
      screen.getByRole("button", { name: "Phê duyệt" }),
    ).toBeInTheDocument();
    expect(mockStartExecution).not.toHaveBeenCalled();
  });

  it("calls startExecution and routes to In Progress only on Approve click", async () => {
    const user = userEvent.setup();
    const approve = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY).find(
      (stage) => stage.stage === "approve",
    );

    renderReview();
    await advanceToStage(user, approve?.title ?? "");

    await user.click(screen.getByRole("button", { name: "Phê duyệt" }));

    expect(mockStartExecution).toHaveBeenCalledTimes(1);
    expect(mockStartExecution).toHaveBeenCalledWith(
      CREATE_HERO_PRODUCT_WORKFLOW_KEY,
    );
    expect(push).toHaveBeenCalledWith(
      "/decisions/in-progress/exec-create_hero_product_1-1",
    );
  });

  it("renders a recoverable not-found state for unsupported workflow keys", () => {
    renderReview("optimize_product_2");

    expect(
      screen.getByRole("status", { name: "Không tìm thấy quy trình" }),
    ).toHaveTextContent("Quy trình không được hỗ trợ");
    expect(screen.getByRole("link", { name: "Về Quyết định" })).toHaveAttribute(
      "href",
      "/decisions",
    );
  });

  it("exposes a navigable analytics deep link on the Analytics stage", async () => {
    const user = userEvent.setup();
    const analytics = getWorkflowReviewStages(
      CREATE_HERO_PRODUCT_WORKFLOW_KEY,
    ).find((stage) => stage.stage === "analytics");

    renderReview();
    await advanceToStage(user, analytics?.title ?? "");

    const analyticsLink = screen.getByRole("link", {
      name: "Xem trên Phân tích",
    });
    expect(analyticsLink).toHaveAttribute(
      "href",
      analytics?.analyticsMetricHref,
    );
  });

  it("supports keyboard navigation between stages via Back and Next", async () => {
    const user = userEvent.setup();
    const stages = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY);

    renderReview();

    const nextButton = screen.getByRole("button", { name: "Tiếp theo" });
    nextButton.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent(
      stages[1].title,
    );

    const backButton = screen.getByRole("button", { name: "Quay lại" });
    backButton.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent(
      stages[0].title,
    );
  });
});
