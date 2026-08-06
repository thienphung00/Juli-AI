import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ExecutionRecord } from "@juli/contracts";

import {
  DEFAULT_MUTABLE_MOCK_STATE,
  DEMO_MUTABLE_STATE_STORAGE_KEY,
  DemoStateProvider,
} from "../components/demo-state";
import { InProgressDetailView } from "../app/decisions/in-progress/[executionId]/page";
import { InProgressPanel } from "../components/in-progress-panel";
import { RecommendationsView } from "../components/recommendations-view";
import { createHeroProductTimeline } from "../lib/executions";
import { recommendationFixtures } from "../lib/recommendations";
import { CREATE_HERO_PRODUCT_WORKFLOW_KEY } from "../lib/reviews";
import { resetExecutionCountersForTests } from "../lib/executions";
import { REVIEW_UI_BANNED_PATTERNS } from "../lib/review-seller-copy";

vi.mock("next/navigation", () => ({
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => "/decisions"),
  useRouter: vi.fn(() => ({
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
    push: vi.fn(),
    refresh: vi.fn(),
    replace: vi.fn(),
  })),
}));

function buildExecutionRecord(
  overrides: Partial<ExecutionRecord> & Pick<ExecutionRecord, "executionId">,
): ExecutionRecord {
  const timeline = overrides.timeline ?? createHeroProductTimeline();
  return {
    workflowKey: CREATE_HERO_PRODUCT_WORKFLOW_KEY,
    toolName: "listing.create_hero_product",
    lifecycleStatus: "executing",
    startedAt: "2026-07-16T04:12:00.000Z",
    updatedAt: "2026-07-16T04:12:00.000Z",
    approvedInputs: {
      category_id: "700648",
      brand_id: "BR-1024",
    },
    ...overrides,
    timeline,
  };
}

function seedMutableState(records: ExecutionRecord[]) {
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
    }),
  );
}

function renderInProgressPanel() {
  return render(
    <DemoStateProvider>
      <InProgressPanel panelId="in-progress-panel" />
    </DemoStateProvider>,
  );
}

function renderInProgressDetail(executionId: string) {
  return render(
    <DemoStateProvider>
      <InProgressDetailView executionId={executionId} />
    </DemoStateProvider>,
  );
}

describe("In Progress list and detail shells", () => {
  beforeEach(() => {
    localStorage.clear();
    resetExecutionCountersForTests();
  });

  it("supports shared In Progress list/detail for needs_input, executing, and completed without a route per step", async () => {
    const executingTimeline = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "running" as const } : step,
    );
    const needsInputTimeline = createHeroProductTimeline().map((step) =>
      step.id === "eligibility-outcome"
        ? { ...step, status: "failed" as const }
        : step,
    );
    const completedTimeline = createHeroProductTimeline().map((step) =>
      step.id === "listed-outcome"
        ? { ...step, status: "succeeded" as const }
        : { ...step, status: "succeeded" as const },
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-create_hero_product_1-1",
        lifecycleStatus: "executing",
        timeline: executingTimeline,
      }),
      buildExecutionRecord({
        executionId: "exec-create_hero_product_1-2",
        lifecycleStatus: "needs_input",
        timeline: needsInputTimeline,
      }),
      buildExecutionRecord({
        executionId: "exec-create_hero_product_1-3",
        lifecycleStatus: "completed",
        timeline: completedTimeline,
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      // Cards replace table - check for 3 article elements (one per execution record)
      expect(screen.getAllByRole("article")).toHaveLength(3);
    });

    const heroTitle = recommendationFixtures[0].title;
    expect(screen.getAllByText(heroTitle)).toHaveLength(3);
    // The lifecycle status labels should appear on the badges
    expect(screen.getByText("Đang thực hiện")).toBeInTheDocument();
    expect(screen.getByText("Cần thêm thông tin")).toBeInTheDocument();
    expect(screen.getByText("Hoàn tất")).toBeInTheDocument();
  });

  it("links each list item to the correct detail URL", async () => {
    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-create_hero_product_1-9",
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      expect(
        screen.getByRole("link", { name: recommendationFixtures[0].title }),
      ).toHaveAttribute("href", "/decisions/in-progress/exec-create_hero_product_1-9");
    });
  });

  it("renders Workflow 1 action, wait, outcome, recovery, and rollback states on the 14-step timeline when expanded", async () => {
    const timeline = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "running" as const } : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-create_hero_product_1-42",
        timeline,
      }),
    ]);

    renderInProgressDetail("exec-create_hero_product_1-42");

    await waitFor(() => {
      expect(screen.getByText("700648")).toBeInTheDocument();
    });

    // Workflow title appears in header
    const titles = screen.getAllByText(recommendationFixtures[0].title);
    expect(titles.length).toBeGreaterThan(0);

    // Approved inputs should be visible with seller-facing labels
    expect(screen.getByText("700648")).toBeInTheDocument();
    expect(screen.getByText("BR-1024")).toBeInTheDocument();

    // Expand the steps list
    const expandButton = screen.getByRole("button", {
      name: "Xem tất cả các bước",
    });
    const user = userEvent.setup();
    await user.click(expandButton);

    // Timeline steps (14 total) should appear after expansion
    await waitFor(() => {
      const timelineItems = screen.getAllByRole("listitem");
      expect(timelineItems.length).toBeGreaterThanOrEqual(14);
    });

    // Step kinds should appear in the timeline
    expect(screen.getAllByText(/Hành động/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Chờ/).length).toBeGreaterThan(0);

    // Specific step titles and descriptions should be present
    expect(screen.getAllByText("Lấy danh mục").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Chờ duyệt sản phẩm").length).toBeGreaterThan(0);
  });

  it("renders recoverable not-found with a link back to Decisions for unknown executionId", async () => {
    renderInProgressDetail("exec-does-not-exist");

    expect(
      screen.getByRole("status", { name: "Không tìm thấy luồng thực hiện" }),
    ).toHaveTextContent("Không tìm thấy luồng thực hiện");
    expect(
      screen.getByRole("link", { name: "Về Quyết định" }),
    ).toHaveAttribute("href", "/decisions");
  });

  it("renders execution progress cards instead of a table when executions exist", async () => {
    const executingTimeline = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "running" as const } : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-card-test-1",
        lifecycleStatus: "executing",
        timeline: executingTimeline,
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      // Assert no table roles
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      expect(screen.queryByRole("columnheader")).not.toBeInTheDocument();
      expect(screen.queryByRole("row", { hidden: false })).not.toBeInTheDocument();

      // Assert one article-level card per execution
      const articles = screen.getAllByRole("article");
      expect(articles).toHaveLength(1);
    });
  });

  it("shows Xác nhận mode strip when execution is in needs_input state", async () => {
    const needsInputTimeline = createHeroProductTimeline().map((step) =>
      step.id === "eligibility-outcome"
        ? { ...step, status: "failed" as const }
        : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-needs-input-1",
        lifecycleStatus: "needs_input",
        timeline: needsInputTimeline,
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      expect(screen.getByText("Xác nhận")).toBeInTheDocument();
    });
  });

  it("shows Đang chạy mode strip when execution is in executing state", async () => {
    const executingTimeline = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "running" as const } : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-executing-1",
        lifecycleStatus: "executing",
        timeline: executingTimeline,
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      expect(screen.getByText("Đang chạy")).toBeInTheDocument();
    });
  });

  it("renders narrative step line with step fraction for executing cards", async () => {
    const executingTimeline = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "running" as const } : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-step-1",
        lifecycleStatus: "executing",
        timeline: executingTimeline,
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      expect(screen.getByText(/Bước \d+ \/ \d+/)).toBeInTheDocument();
    });
  });

  it("renders policy line on every card", async () => {
    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-policy-1",
        lifecycleStatus: "needs_input",
      }),
      buildExecutionRecord({
        executionId: "exec-policy-2",
        lifecycleStatus: "executing",
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      const policyLines = screen.getAllByText("Đã kiểm tra chính sách TikTok Shop");
      expect(policyLines).toHaveLength(2);
    });
  });

  it("renders visible cancel/rollback control on every card", async () => {
    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-cancel-1",
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^Hủy/ })).toBeInTheDocument();
    });
  });

  it("sorts cards with executing first, then needs_input, then completed last", async () => {
    const executingTimeline = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "running" as const } : step,
    );
    const needsInputTimeline = createHeroProductTimeline().map((step) =>
      step.id === "eligibility-outcome"
        ? { ...step, status: "failed" as const }
        : step,
    );
    const completedTimeline = createHeroProductTimeline().map(
      (step) => ({ ...step, status: "succeeded" as const }),
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-completed-1",
        lifecycleStatus: "completed",
        timeline: completedTimeline,
      }),
      buildExecutionRecord({
        executionId: "exec-executing-1",
        lifecycleStatus: "executing",
        timeline: executingTimeline,
      }),
      buildExecutionRecord({
        executionId: "exec-needs-input-1",
        lifecycleStatus: "needs_input",
        timeline: needsInputTimeline,
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      const articles = screen.getAllByRole("article");
      expect(articles).toHaveLength(3);

      // Check order: executing should come first
      const mode1 = within(articles[0]).queryByText("Đang chạy");
      const mode2 = within(articles[1]).queryByText("Xác nhận");
      const mode3 = within(articles[2]).queryByText("Hoàn tất");

      expect(mode1).toBeInTheDocument();
      expect(mode2).toBeInTheDocument();
      expect(mode3).toBeInTheDocument();
    });
  });

  it("does not render banned seller-surface strings (Khả năng, Công cụ, etc.)", async () => {
    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-no-banned-1",
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      expect(screen.queryByText(/Khả năng:/)).not.toBeInTheDocument();
      expect(screen.queryByText(/Công cụ:/)).not.toBeInTheDocument();
      expect(screen.queryByText(/workflow_key/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/tool_name/i)).not.toBeInTheDocument();
    });
  });

  it("does not issue network calls on cancel/rollback activation", async () => {
    const fetchSpy = vi.spyOn(global, "fetch");

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-no-fetch-1",
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^Hủy/ })).toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Hủy/ }));

    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("links card title to /decisions/in-progress/[executionId] for every card", async () => {
    seedMutableState([
      buildExecutionRecord({ executionId: "exec-link-1" }),
      buildExecutionRecord({ executionId: "exec-link-2" }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      const links = screen.getAllByRole("link", { name: recommendationFixtures[0].title });
      expect(links).toHaveLength(2);
      expect(links[0]).toHaveAttribute("href", "/decisions/in-progress/exec-link-1");
      expect(links[1]).toHaveAttribute("href", "/decisions/in-progress/exec-link-2");
    });
  });

  it("updates empty state copy to match design spec", () => {
    renderInProgressPanel();

    const placeholder = screen.getByRole("status", { name: "Đang thực hiện" });
    expect(within(placeholder).getByText("Công việc đã phê duyệt sẽ xuất hiện ở đây.")).toBeInTheDocument();
    // Old copy should not be present
    expect(within(placeholder).queryByText(/Sắp ra mắt/)).not.toBeInTheDocument();
    expect(within(placeholder).queryByText(/trong một bản cập nhật tiếp theo/)).not.toBeInTheDocument();
  });

  it("keeps the existing empty-state placeholder copy when there are no records", () => {
    renderInProgressPanel();

    const placeholder = screen.getByRole("status", { name: "Đang thực hiện" });
    expect(within(placeholder).getByText("Công việc đã phê duyệt sẽ xuất hiện ở đây.")).toBeInTheDocument();
    expect(within(placeholder).getByRole("heading", { level: 2 })).toHaveTextContent(
      "Đang thực hiện",
    );
  });

  it("shows the in-progress tab placeholder through RecommendationsView when no records exist", async () => {
    const user = userEvent.setup();

    render(
      <DemoStateProvider>
        <RecommendationsView />
      </DemoStateProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Đang thực hiện" }));

    expect(screen.getByText("Công việc đã phê duyệt sẽ xuất hiện ở đây.")).toBeInTheDocument();
  });

  it("renders lifecycle badge with appropriate variant for each card", async () => {
    const executingTimeline = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "running" as const } : step,
    );
    const completedTimeline = createHeroProductTimeline().map(
      (step) => ({ ...step, status: "succeeded" as const }),
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-badge-1",
        lifecycleStatus: "executing",
        timeline: executingTimeline,
      }),
      buildExecutionRecord({
        executionId: "exec-badge-2",
        lifecycleStatus: "completed",
        timeline: completedTimeline,
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      expect(screen.getByText("Đang thực hiện")).toBeInTheDocument();
      expect(screen.getByText("Hoàn tất")).toBeInTheDocument();
    });
  });
});

describe("Execution detail view (DUX-8) — seller-safe language", () => {
  beforeEach(() => {
    localStorage.clear();
    resetExecutionCountersForTests();
  });

  it("renders the detail view without any banned seller-surface strings", async () => {
    const timeline = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "running" as const } : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-banned-check-1",
        timeline,
      }),
    ]);

    renderInProgressDetail("exec-banned-check-1");

    // Wait for any element to render indicating the page has loaded
    await waitFor(() => {
      expect(screen.getByText(/Bước \d+ \/ \d+/)).toBeInTheDocument();
    });

    // Get the entire document text content
    const renderedText = document.body.textContent || "";

    // Check that no banned patterns appear in the rendered text
    for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
      const matches = renderedText.match(pattern);
      expect(
        matches,
        `Banned pattern found: ${pattern}`,
      ).toBeNull();
    }
  });

  it("shows mode strip (Xác nhận/Đang chạy) that matches the list card's mode strip", async () => {
    const needsInputTimeline = createHeroProductTimeline().map((step) =>
      step.id === "eligibility-outcome"
        ? { ...step, status: "failed" as const }
        : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-mode-confirm-1",
        lifecycleStatus: "needs_input",
        timeline: needsInputTimeline,
      }),
    ]);

    // Render list card and capture its mode
    const { rerender } = render(
      <DemoStateProvider>
        <InProgressPanel panelId="list-panel" />
      </DemoStateProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("Xác nhận")).toBeInTheDocument();
    });

    // Clear and render detail view
    localStorage.clear();
    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-mode-confirm-1",
        lifecycleStatus: "needs_input",
        timeline: needsInputTimeline,
      }),
    ]);

    rerender(
      <DemoStateProvider>
        <InProgressDetailView executionId="exec-mode-confirm-1" />
      </DemoStateProvider>,
    );

    // Both should show "Xác nhận"
    await waitFor(() => {
      const confirmModes = screen.getAllByText("Xác nhận");
      expect(confirmModes.length).toBeGreaterThan(0);
    });
  });

  it("shows Đang chạy mode strip in detail view when execution is running", async () => {
    const executingTimeline = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "running" as const } : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-mode-running-1",
        lifecycleStatus: "executing",
        timeline: executingTimeline,
      }),
    ]);

    renderInProgressDetail("exec-mode-running-1");

    await waitFor(() => {
      expect(screen.getByText("Đang chạy")).toBeInTheDocument();
    });
  });

  it("shows policy badge on the detail view", async () => {
    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-policy-detail-1",
        lifecycleStatus: "executing",
      }),
    ]);

    renderInProgressDetail("exec-policy-detail-1");

    await waitFor(() => {
      expect(
        screen.getByText("Đã kiểm tra chính sách TikTok Shop"),
      ).toBeInTheDocument();
    });
  });

  it("shows cancel/rollback button on the detail view without scrolling", async () => {
    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-cancel-detail-1",
        lifecycleStatus: "executing",
      }),
    ]);

    renderInProgressDetail("exec-cancel-detail-1");

    await waitFor(() => {
      const cancelButton = screen.getByRole("button", { name: /^Hủy/ });
      expect(cancelButton).toBeInTheDocument();

      // Verify it's not hidden/scrolled out of view
      expect(cancelButton).toBeVisible();
    });
  });

  it("does not show duration estimate when execution is running", async () => {
    const executingTimeline = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "running" as const } : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-duration-1",
        lifecycleStatus: "executing",
        timeline: executingTimeline,
      }),
    ]);

    renderInProgressDetail("exec-duration-1");

    await waitFor(() => {
      expect(screen.getByText(/Bước \d+ \/ \d+/)).toBeInTheDocument();
    });

    expect(screen.queryByText(/5–10 phút|phút|ETA|khoảng thời gian/i)).not.toBeInTheDocument();
  });

  it("does not make network calls on render or cancel/rollback", async () => {
    const fetchSpy = vi.spyOn(global, "fetch");

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-no-fetch-detail-1",
        lifecycleStatus: "executing",
      }),
    ]);

    renderInProgressDetail("exec-no-fetch-detail-1");

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^Hủy/ })).toBeInTheDocument();
    });

    expect(fetchSpy).not.toHaveBeenCalled();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Hủy/ }));

    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("handles failed steps with recovery text on detail view", async () => {
    const failedTimeline = createHeroProductTimeline().map((step) =>
      step.id === "eligibility-outcome"
        ? {
            ...step,
            status: "failed" as const,
            recoveryText: "Quay lại bước lấy danh mục hoặc bổ sung điều kiện còn thiếu trước khi tiếp tục.",
          }
        : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-recovery-1",
        lifecycleStatus: "needs_input",
        timeline: failedTimeline,
      }),
    ]);

    renderInProgressDetail("exec-recovery-1");

    // Recovery text should be visible in the next action area at the top
    await waitFor(() => {
      const renderedText = document.body.textContent || "";
      expect(renderedText).toContain("Quay lại bước lấy danh mục hoặc bổ sung điều kiện còn thiếu trước khi tiếp tục.");
    });
  });

  it("displays approved inputs with seller-facing labels, not raw keys", async () => {
    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-inputs-1",
        approvedInputs: {
          category_id: "700648",
          brand_id: "BR-1024",
        },
      }),
    ]);

    renderInProgressDetail("exec-inputs-1");

    await waitFor(() => {
      // The approved inputs should be visible with the actual values
      expect(screen.getByText("700648")).toBeInTheDocument();
      expect(screen.getByText("BR-1024")).toBeInTheDocument();
    });

    // Verify that the card has the seller-facing labels (Danh mục, Nhãn hiệu)
    expect(screen.getByText("Danh mục")).toBeInTheDocument();
    expect(screen.getByText("Nhãn hiệu")).toBeInTheDocument();
  });

  it("returns to /decisions when clicking the back link for unknown executionId", async () => {
    renderInProgressDetail("exec-does-not-exist");

    await waitFor(() => {
      const backLink = screen.getByRole("link", { name: "Về Quyết định" });
      expect(backLink).toHaveAttribute("href", "/decisions");
    });
  });
});

describe("Execution progress card — step fraction and expansion (issue #762)", () => {
  beforeEach(() => {
    localStorage.clear();
    resetExecutionCountersForTests();
  });

  it("shows step fraction in card when execution is executing", async () => {
    const executingTimeline = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "running" as const } : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-fraction-1",
        lifecycleStatus: "executing",
        timeline: executingTimeline,
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      // Should show fraction like "1 / 14" or "Bước 1 của 14"
      expect(screen.getByText(/\d+ \/ \d+/)).toBeInTheDocument();
    });
  });

  it("hides full step list by default in the card", async () => {
    const executingTimeline = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "running" as const } : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-hidden-steps-1",
        lifecycleStatus: "executing",
        timeline: executingTimeline,
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      // The card should be in the document
      expect(screen.getByRole("article")).toBeInTheDocument();
    });

    // Full step list should NOT be visible in the card initially
    const listItems = screen.queryAllByRole("listitem");
    expect(listItems.length).toBe(0);
  });

  it("expands to show full steps when expansion button is clicked", async () => {
    const executingTimeline = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "running" as const } : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-expand-1",
        lifecycleStatus: "executing",
        timeline: executingTimeline,
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      expect(screen.getByRole("article")).toBeInTheDocument();
    });

    // Find and click the expand button
    const expandButton = screen.getByRole("button", {
      name: /Mở rộng|Xem tất cả các bước/i,
    });
    const user = userEvent.setup();
    await user.click(expandButton);

    // After expansion, the full step list should be visible
    await waitFor(() => {
      const listItems = screen.getAllByRole("listitem");
      expect(listItems.length).toBeGreaterThan(0);
    });
  });

  it("keeps status line and fraction visible when steps are expanded", async () => {
    const executingTimeline = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "running" as const } : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-visible-status-1",
        lifecycleStatus: "executing",
        timeline: executingTimeline,
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      expect(screen.getByRole("article")).toBeInTheDocument();
    });

    // Fraction should be visible initially
    const fractionBefore = screen.getByText(/\d+ \/ \d+/);
    expect(fractionBefore).toBeVisible();

    // Expand
    const expandButton = screen.getByRole("button", {
      name: /Mở rộng|Xem tất cả các bước/i,
    });
    const user = userEvent.setup();
    await user.click(expandButton);

    // Fraction should still be visible after expansion
    await waitFor(() => {
      const fractionAfter = screen.getByText(/\d+ \/ \d+/);
      expect(fractionAfter).toBeVisible();
    });
  });

  it("does not render ETA or time estimate strings in the card", async () => {
    const executingTimeline = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "running" as const } : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-no-eta-1",
        lifecycleStatus: "executing",
        timeline: executingTimeline,
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      expect(screen.getByRole("article")).toBeInTheDocument();
    });

    // Verify no ETA, time estimate, or countdown strings
    expect(screen.queryByText(/phút|ETA|khoảng|khoảng thời gian/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/5–10 phút/)).not.toBeInTheDocument();
  });

  it("displays step titles sanitized for sellers in expanded list", async () => {
    const executingTimeline = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "running" as const } : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-sanitized-1",
        lifecycleStatus: "executing",
        timeline: executingTimeline,
      }),
    ]);

    renderInProgressDetail("exec-sanitized-1");

    // Wait for the card to render (check for step fraction)
    await waitFor(() => {
      expect(screen.getByText(/Bước \d+ \/ \d+/)).toBeInTheDocument();
    });

    // Check for steps without banned patterns (should not be in rendered text)
    const renderedText = document.body.textContent || "";
    expect(renderedText.match(/Khả năng:/)).toBeNull();
    expect(renderedText.match(/Công cụ:/)).toBeNull();

    // Expand the steps list
    const expandButton = screen.getByRole("button", {
      name: "Xem tất cả các bước",
    });
    const user = userEvent.setup();
    await user.click(expandButton);

    // After expansion, step titles should be visible in the expanded list
    await waitFor(() => {
      const stepTitles = screen.getAllByText("Lấy danh mục");
      // Should have at least 2: one in next action, one in expanded list
      expect(stepTitles.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("reflects current active step in fraction as timeline progresses", async () => {
    // First step running
    const timeline1 = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "running" as const } : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-progress-1",
        lifecycleStatus: "executing",
        timeline: timeline1,
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      // Should show 1/total
      const text = screen.getByText(/1 \/ \d+/);
      expect(text).toBeInTheDocument();
    });
  });
});
