import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ExecutionRecord } from "@juli/contracts";

import {
  DEFAULT_MUTABLE_MOCK_STATE,
  DEMO_MUTABLE_STATE_STORAGE_KEY,
  DemoStateProvider,
} from "../components/demo-state";
import { InProgressPanel } from "../components/in-progress-panel";
import { RecommendationsView } from "../components/recommendations-view";
import { createHeroProductTimeline, resetExecutionCountersForTests } from "../lib/executions";
import { CREATE_HERO_PRODUCT_WORKFLOW_KEY } from "../lib/reviews";
import { REVIEW_UI_BANNED_PATTERNS } from "../lib/review-seller-copy";
import { RUN_LEDGER_EMPTY_STATE } from "../lib/run-ledger/copy";

/**
 * List-shell coverage for `InProgressPanel`'s legacy mock-execution renderer
 * -- the OTHER 10 workflows' needs_input / executing / completed
 * `ExecutionRecord` cards, functionally unchanged by issue #1318 (see the
 * component doc comment). These assertions originally lived in
 * `in-progress.test.tsx` (deleted when #1318 split the file into
 * `in-progress-detail-view.test.tsx` + `run-ledger-panel.test.tsx`) but were
 * dropped in that split rather than ported. Restored here, adapted to the
 * now-composed panel: the ledger's own `fetch` is stubbed to resolve zero
 * runs so only the legacy `<article>` cards are on the page, keeping these
 * assertions about the *other 10 workflows* uncontaminated by the run
 * ledger's own (already covered) `run-ledger-panel.test.tsx` suite.
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

function renderInProgressPanel() {
  return render(
    <DemoStateProvider>
      <InProgressPanel panelId="in-progress-panel" />
    </DemoStateProvider>,
  );
}

describe("In Progress list shell — the other 10 workflows' legacy execution cards (#1318 regression guard)", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    localStorage.clear();
    resetExecutionCountersForTests();
    // The run ledger (issue #1318) polls `GET /v1/demo/runs` from the same
    // panel. Stub it to zero runs so these legacy-card assertions are never
    // contaminated by run-ledger sections/cards -- that surface has its own
    // dedicated coverage in `run-ledger-panel.test.tsx`.
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, data: [] }),
    } as Response);
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
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
    const completedTimeline = createHeroProductTimeline().map((step) => ({
      ...step,
      status: "succeeded" as const,
    }));

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

      // Sort order: executing, then needs_input, then completed.
      expect(articles[0]).toHaveAttribute("data-lifecycle-status", "executing");
      expect(articles[1]).toHaveAttribute("data-lifecycle-status", "needs_input");
      expect(articles[2]).toHaveAttribute("data-lifecycle-status", "completed");

      expect(within(articles[0]).getByText("Đang chạy")).toBeInTheDocument();
      expect(within(articles[1]).getByText("Xác nhận")).toBeInTheDocument();
      expect(within(articles[2]).getByText("Hoàn tất")).toBeInTheDocument();
    });
  });

  it("renders visible cancel/rollback control on every card", async () => {
    seedMutableState([
      buildExecutionRecord({ executionId: "exec-cancel-1" }),
      buildExecutionRecord({ executionId: "exec-cancel-2" }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      const cancelButtons = screen.getAllByRole("button", { name: /^Hủy/ });
      expect(cancelButtons).toHaveLength(2);
      for (const button of cancelButtons) {
        expect(button).toBeVisible();
      }
    });
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
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      expect(screen.queryByRole("columnheader")).not.toBeInTheDocument();
      expect(screen.queryByRole("row", { hidden: false })).not.toBeInTheDocument();

      const articles = screen.getAllByRole("article");
      expect(articles).toHaveLength(1);
    });
  });

  it("renders lifecycle badge with appropriate variant for each card", async () => {
    const executingTimeline = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "running" as const } : step,
    );
    const completedTimeline = createHeroProductTimeline().map((step) => ({
      ...step,
      status: "succeeded" as const,
    }));

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

  it("does not render banned seller-surface strings (Khả năng, Công cụ, etc.)", async () => {
    seedMutableState([
      buildExecutionRecord({ executionId: "exec-no-banned-1" }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      expect(screen.getByRole("article")).toBeInTheDocument();
    });

    const renderedText = document.body.textContent ?? "";
    for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
      expect(renderedText.match(pattern), `Banned pattern found: ${pattern}`).toBeNull();
    }
    expect(screen.queryByText(/Khả năng:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Công cụ:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/workflow_key/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/tool_name/i)).not.toBeInTheDocument();
  });

  it("shows the current dictionary-governed empty state copy, not the pre-#1318 placeholder", async () => {
    // The empty-state placeholder text was re-scoped to the run ledger's own
    // dictionary-governed copy by #1318 (`empty.decisions.in_progress_filtered`,
    // `run-ledger/copy.ts`). This guards the *current* spec's copy the same
    // way the pre-#1318 test guarded its own spec's copy -- adapted, not
    // weakened, because the underlying string this test protects legitimately
    // changed under the same issue that dropped the original assertion.
    //
    // The empty-state branch only renders once the ledger's poll resolves
    // (`ledgerStatus !== "loading"`) -- unlike the pre-#1318 shell, this is
    // now async even with zero mock records.
    renderInProgressPanel();

    const placeholder = await screen.findByRole("status", { name: "Đang thực hiện" });
    expect(within(placeholder).getByText(RUN_LEDGER_EMPTY_STATE)).toBeInTheDocument();

    // Pre-#1318 copy should not be present.
    expect(
      within(placeholder).queryByText("Công việc đã phê duyệt sẽ xuất hiện ở đây."),
    ).not.toBeInTheDocument();
    expect(within(placeholder).queryByText(/Sắp ra mắt/)).not.toBeInTheDocument();
    expect(
      within(placeholder).queryByText(/trong một bản cập nhật tiếp theo/),
    ).not.toBeInTheDocument();
  });

  it("keeps the existing empty-state placeholder shell (status role, heading) when there are no runs or records", async () => {
    renderInProgressPanel();

    const placeholder = await screen.findByRole("status", { name: "Đang thực hiện" });
    expect(within(placeholder).getByText(RUN_LEDGER_EMPTY_STATE)).toBeInTheDocument();
    expect(within(placeholder).getByRole("heading", { level: 2 })).toHaveTextContent(
      "Đang thực hiện",
    );
  });

  it("shows the in-progress tab placeholder through RecommendationsView when no runs exist", async () => {
    const user = userEvent.setup();

    render(
      <DemoStateProvider>
        <RecommendationsView />
      </DemoStateProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Đang thực hiện" }));

    await waitFor(() => {
      expect(screen.getByText(RUN_LEDGER_EMPTY_STATE)).toBeInTheDocument();
    });
  });

  it("shows Xác nhận mode strip on the list card when execution is in needs_input state", async () => {
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

  it("shows Đang chạy mode strip on the list card when execution is in executing state", async () => {
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
});
