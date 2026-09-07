import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ExecutionRecord } from "@juli/contracts";

import {
  DEFAULT_MUTABLE_MOCK_STATE,
  DEMO_MUTABLE_STATE_STORAGE_KEY,
  DemoStateProvider,
} from "../components/demo-state";
import { InProgressDetailView } from "../app/decisions/in-progress/[executionId]/page";
import { createHeroProductTimeline } from "../lib/executions";
import { recommendationFixtures } from "../lib/recommendations";
import { CREATE_HERO_PRODUCT_WORKFLOW_KEY } from "../lib/reviews";
import { resetExecutionCountersForTests } from "../lib/executions";
import { REVIEW_UI_BANNED_PATTERNS } from "../lib/review-seller-copy";

/**
 * Coverage for `InProgressDetailView`
 * (`app/decisions/in-progress/[executionId]/page.tsx`), the mock-state
 * per-execution detail route. Untouched by issue #1318 (In-Progress becomes
 * the run ledger): that slice replaces the LIST panel
 * (`components/in-progress-panel.tsx`) with a real polled-read-model
 * ledger, but explicitly leaves this mock detail view and the mock state
 * it reads intact -- deleting the mock is #1320's job, not this one. These
 * tests were originally interleaved with the (now-replaced) mock list
 * panel's own tests in `in-progress.test.tsx`; split out here, unchanged,
 * because this component's behavior did not change.
 */

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

function renderInProgressDetail(executionId: string) {
  return render(
    <DemoStateProvider>
      <InProgressDetailView executionId={executionId} />
    </DemoStateProvider>,
  );
}

describe("In Progress detail view — shared shell for needs_input, executing, and completed", () => {
  beforeEach(() => {
    localStorage.clear();
    resetExecutionCountersForTests();
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
});
