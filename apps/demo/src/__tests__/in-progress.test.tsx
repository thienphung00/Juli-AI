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

  it("renders lifecycle badges with the exact three Vietnamese labels and workflow title", async () => {
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
      expect(screen.getAllByRole("row")).toHaveLength(4);
    });

    const heroTitle = recommendationFixtures[0].title;
    expect(screen.getAllByText(heroTitle)).toHaveLength(3);
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

  it("renders identity, approved inputs, and the full 14-step timeline with kinds and recovery text", async () => {
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

  it("keeps the existing empty-state placeholder copy when there are no records", () => {
    renderInProgressPanel();

    const placeholder = screen.getByRole("status", { name: "Đang thực hiện" });
    expect(within(placeholder).getByText("Sắp ra mắt")).toBeInTheDocument();
    expect(within(placeholder).getByRole("heading", { level: 2 })).toHaveTextContent(
      "Đang thực hiện",
    );
    expect(placeholder).toHaveTextContent(
      "Công việc đã phê duyệt sẽ xuất hiện ở đây trong một bản cập nhật tiếp theo.",
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

    expect(screen.getByText("Sắp ra mắt")).toBeInTheDocument();
  });
});
