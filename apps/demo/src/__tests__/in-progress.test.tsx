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

  it("renders Workflow 1 action, wait, outcome, recovery, and rollback states on the 14-step timeline", async () => {
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
      expect(screen.getByText("exec-create_hero_product_1-42")).toBeInTheDocument();
    });

    expect(screen.getByText(CREATE_HERO_PRODUCT_WORKFLOW_KEY)).toBeInTheDocument();
    expect(screen.getByText("listing.create_hero_product")).toBeInTheDocument();
    expect(screen.getByText("700648")).toBeInTheDocument();
    expect(screen.getByText("BR-1024")).toBeInTheDocument();

    const timelineItems = screen.getAllByRole("listitem");
    expect(timelineItems).toHaveLength(14);

    expect(screen.getAllByText(/Hành động/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Chờ/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Kết quả/).length).toBeGreaterThan(0);

    expect(
      screen.getByText(
        "Quay lại bước lấy danh mục hoặc bổ sung điều kiện còn thiếu trước khi tiếp tục.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Lấy danh mục")).toBeInTheDocument();
    expect(screen.getByText("Chờ duyệt sản phẩm")).toBeInTheDocument();
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

  it("renders narrative step line with Bước format and duration for executing cards", async () => {
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
      const activeStep = executingTimeline.find((s) => s.status === "running");
      expect(screen.getByText(`Bước ${activeStep?.stepNumber}: ${activeStep?.title}`)).toBeInTheDocument();
      expect(screen.getByText("5–10 phút")).toBeInTheDocument();
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
