import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RecommendationReview } from "../components/recommendation-review";
import {
  buildReviewInputDefaults,
  buildReviewInputDefaultsForWorkflow,
  CREATE_HERO_PRODUCT_WORKFLOW_KEY,
  getWorkflowReviewStages,
  OPTIMIZE_PRODUCT_WORKFLOW_KEY,
} from "../lib/reviews";
import {
  REVIEW_UI_BANNED_PATTERNS,
  SELLER_APPROVE_GATE,
} from "../lib/review-seller-copy";
import { confirmApproveThroughGate } from "./review-test-helpers";

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
  workflowKey = CREATE_HERO_PRODUCT_WORKFLOW_KEY,
) {
  const stages = getWorkflowReviewStages(workflowKey);
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

  it("links back to the decisions list with highlight query for the active workflow", () => {
    renderReview();

    expect(
      screen.getByRole("link", { name: "Về danh sách đề xuất" }),
    ).toHaveAttribute(
      "href",
      `/decisions?highlight=${CREATE_HERO_PRODUCT_WORKFLOW_KEY}`,
    );
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

  it("renders Preview-stage seller summary and draft values", async () => {
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

    const stageBody = screen.getByTestId("review-stage-body");
    approve?.body.split("\n\n").forEach((chunk) => {
      expect(stageBody).toHaveTextContent(chunk);
    });
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

  it("opens the approval gate before starting execution", async () => {
    const user = userEvent.setup();
    const approve = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY).find(
      (stage) => stage.stage === "approve",
    );

    renderReview();
    await advanceToStage(user, approve?.title ?? "");

    await user.click(screen.getByRole("button", { name: "Phê duyệt" }));

    expect(screen.getByRole("dialog")).toHaveTextContent(
      SELLER_APPROVE_GATE.description,
    );
    expect(mockStartExecution).not.toHaveBeenCalled();
  });

  it("calls startExecution and routes to In Progress only after gate confirm", async () => {
    const user = userEvent.setup();
    const approve = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY).find(
      (stage) => stage.stage === "approve",
    );

    renderReview();
    await advanceToStage(user, approve?.title ?? "");

    await confirmApproveThroughGate(user);

    expect(mockStartExecution).toHaveBeenCalledTimes(1);
    expect(mockStartExecution).toHaveBeenCalledWith(
      CREATE_HERO_PRODUCT_WORKFLOW_KEY,
    );
    expect(push).toHaveBeenCalledWith(
      "/decisions/in-progress/exec-create_hero_product_1-1",
    );
  });

  it("renders a recoverable not-found state for unsupported workflow keys", () => {
    renderReview("prevent_return_8b_fbt");

    expect(
      screen.getByRole("status", { name: "Không tìm thấy quy trình" }),
    ).toHaveTextContent("Quy trình không được hỗ trợ");
    expect(screen.getByRole("link", { name: "Về Quyết định" })).toHaveAttribute(
      "href",
      "/decisions",
    );
  });

  it("renders review stages for prevent_cancellation_8a", () => {
    const stages = getWorkflowReviewStages("prevent_cancellation_8a");
    expect(stages).toHaveLength(5);

    renderReview("prevent_cancellation_8a");

    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent(
      stages[0].title,
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

  it("does not render banned jargon across all review stages", async () => {
    const user = userEvent.setup();
    const stages = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY);

    renderReview();

    for (const [index] of stages.entries()) {
      const surfaceText = screen.getByTestId("review-stage-body").textContent ?? "";

      for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
        expect(surfaceText).not.toMatch(pattern);
      }

      if (index < stages.length - 1) {
        await user.click(screen.getByRole("button", { name: "Tiếp theo" }));
      }
    }
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

  it("shows suggestion glow and label on editable prefilled fields in Inputs stage", async () => {
    const user = userEvent.setup();
    const inputs = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY).find(
      (stage) => stage.stage === "inputs",
    );

    renderReview();
    await advanceToStage(user, inputs?.title ?? "");

    // Verify the suggestion badge is visible somewhere in the Inputs stage
    const suggestionBadges = screen.getAllByText("Gợi ý bởi Juli");
    expect(suggestionBadges.length).toBeGreaterThan(0);

    // Verify that at least one input has the suggestion glow class
    const inputsWithSuggestion = screen.getAllByRole("textbox").filter((input) =>
      input.classList.contains("juli-form__input--suggestion"),
    );
    expect(inputsWithSuggestion.length).toBeGreaterThan(0);
  });

  it("removes suggestion glow and label when editing a prefilled field", async () => {
    const user = userEvent.setup();
    const inputs = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY).find(
      (stage) => stage.stage === "inputs",
    );

    renderReview();
    await advanceToStage(user, inputs?.title ?? "");

    // Find the first input with suggestion glow
    const inputsWithGlow = screen.getAllByRole("textbox").filter((input) =>
      input.classList.contains("juli-form__input--suggestion"),
    );
    expect(inputsWithGlow.length).toBeGreaterThan(0);

    const brandInput = inputsWithGlow[0] as HTMLInputElement;
    const originalValue = brandInput.value;

    // Edit the field
    await user.clear(brandInput);
    await user.type(brandInput, "Edited Brand");

    // After editing, the glow should be removed
    expect(brandInput).not.toHaveClass("juli-form__input--suggestion");
  });

  it("restores suggestion glow and label when value is restored to prefill", async () => {
    const user = userEvent.setup();
    const inputs = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY).find(
      (stage) => stage.stage === "inputs",
    );

    renderReview();
    await advanceToStage(user, inputs?.title ?? "");

    // Find the first input with suggestion glow
    const inputsWithGlow = screen.getAllByRole("textbox").filter((input) =>
      input.classList.contains("juli-form__input--suggestion"),
    );
    expect(inputsWithGlow.length).toBeGreaterThan(0);

    const brandInput = inputsWithGlow[0] as HTMLInputElement;
    const originalValue = brandInput.value;

    // Edit the field
    await user.clear(brandInput);
    await user.type(brandInput, "Edited Brand");

    expect(brandInput).not.toHaveClass("juli-form__input--suggestion");

    // Restore to original value
    await user.clear(brandInput);
    await user.type(brandInput, originalValue);

    // Glow should be restored
    expect(brandInput).toHaveClass("juli-form__input--suggestion");
  });

  it("does not show suggestion glow or label on non-editable fields", async () => {
    const user = userEvent.setup();
    const inputs = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY).find(
      (stage) => stage.stage === "inputs",
    );

    renderReview();
    await advanceToStage(user, inputs?.title ?? "");

    // Find all disabled inputs (non-editable fields)
    const disabledInputs = screen.getAllByRole("textbox").filter((input) =>
      input.hasAttribute("disabled"),
    );

    // Verify that disabled inputs don't have the suggestion glow
    for (const input of disabledInputs) {
      expect(input).not.toHaveClass("juli-form__input--suggestion");
    }
  });

  it("renders Preview stage with edited values instead of prefilled defaults", async () => {
    const user = userEvent.setup();
    const inputs = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY).find(
      (stage) => stage.stage === "inputs",
    );
    const preview = getWorkflowReviewStages(CREATE_HERO_PRODUCT_WORKFLOW_KEY).find(
      (stage) => stage.stage === "preview",
    );

    renderReview();
    await advanceToStage(user, inputs?.title ?? "");

    // Find the first input with suggestion glow and edit it
    const inputsWithGlow = screen.getAllByRole("textbox").filter((input) =>
      input.classList.contains("juli-form__input--suggestion"),
    );
    expect(inputsWithGlow.length).toBeGreaterThan(0);

    const editedInput = inputsWithGlow[0] as HTMLInputElement;
    const editedValue = "EDITED-VALUE-TEST";
    await user.clear(editedInput);
    await user.type(editedInput, editedValue);

    // Advance to Preview
    await advanceToStage(user, preview?.title ?? "");

    // The preview summary should show the edited value
    const summary = screen.getByTestId("review-draft-summary");
    expect(summary).toHaveTextContent(editedValue);
  });
});

describe("RecommendationReview routing between spine and five-stage review", () => {
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
    ]) {
      const { unmount } = renderReview(workflowKey);

      expect(screen.getByTestId("plan-review-card")).toBeInTheDocument();
      expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Tiếp theo" }),
      ).not.toBeInTheDocument();

      unmount();
    }
  });

  it("keeps every other workflow on the five-stage review", () => {
    for (const workflowKey of [
      CREATE_HERO_PRODUCT_WORKFLOW_KEY,
      "replenish_inventory_3",
      "clear_excess_4",
      "process_order_5",
      "create_activity_7a",
      "update_activity_7c",
      "prevent_cancellation_8a",
      "prevent_return_8b",
      "prevent_refund_8c",
    ]) {
      const { unmount } = renderReview(workflowKey);

      expect(screen.queryByTestId("plan-review-card")).not.toBeInTheDocument();
      expect(screen.getByRole("tablist")).toBeInTheDocument();
      expect(getWorkflowReviewStages(workflowKey)).toHaveLength(5);

      unmount();
    }
  });
});
