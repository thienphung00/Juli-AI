import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkflowRunListItem } from "@juli/contracts";

import { InProgressPanel } from "../components/in-progress-panel";
import { RecommendationsView } from "../components/recommendations-view";
import { DemoStateProvider } from "../components/demo-state";
import { RUN_LEDGER_POLL_INTERVAL_MS } from "../lib/run-ledger/panel-config";
import { RUN_TERMINAL_STATE_COPY } from "../lib/run-ledger/copy";

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

function buildRun(overrides: Partial<WorkflowRunListItem> & Pick<WorkflowRunListItem, "id">): WorkflowRunListItem {
  return {
    status: "running",
    stop_reason: null,
    product_name: "Áo thun cotton nam",
    created_at: "2026-08-25T09:00:00.000Z",
    completed_at: null,
    running_seconds_elapsed: 12,
    latest_narration: null,
    decision_summary: null,
    ...overrides,
  };
}

function mockRunsResponse(data: WorkflowRunListItem[]) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ success: true, data }),
  } as Response;
}

function renderPanel() {
  return render(
    <DemoStateProvider>
      <InProgressPanel panelId="in-progress-panel" />
    </DemoStateProvider>,
  );
}

describe("Run ledger — In-Progress becomes the run ledger (#1318)", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(mockRunsResponse([]));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("polls GET /v1/demo/runs, never the SSE event stream endpoint", async () => {
    renderPanel();

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("/v1/demo/runs");
    expect(String(url)).not.toContain("/events");
  });

  it("re-fetches on the poll cadence", async () => {
    vi.useFakeTimers();
    renderPanel();

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(RUN_LEDGER_POLL_INTERVAL_MS);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(RUN_LEDGER_POLL_INTERVAL_MS);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("shows the dictionary-governed empty state when there are no runs", async () => {
    renderPanel();

    await waitFor(() => {
      expect(
        screen.getByText("Chưa có quyết định nào đang thực hiện."),
      ).toBeInTheDocument();
    });
  });

  it("renders three landmark sections, waiting-on-you pinned above running above finished", async () => {
    const waiting = buildRun({
      id: "run-waiting",
      status: "waiting_approval",
      product_name: "Áo thun waiting",
      decision_summary: {
        tool_call_id: "call-1",
        expires_at: "2026-08-25T13:58:00.000Z",
      },
    });
    const running = buildRun({ id: "run-running", status: "running", product_name: "Áo thun running" });
    const finished = buildRun({
      id: "run-finished",
      status: "completed",
      stop_reason: "final_response",
      product_name: "Áo thun finished",
    });

    fetchMock.mockResolvedValue(mockRunsResponse([finished, running, waiting]));

    renderPanel();

    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 2, name: "Đang chờ bạn" })).toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { level: 2, name: "Đang chạy" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Hoàn tất" })).toBeInTheDocument();

    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(["Đang chờ bạn", "Đang chạy", "Hoàn tất"]);
  });

  it("shows a queued run with no narration in the running section — proving the list is a poll, not a stream", async () => {
    const queued = buildRun({
      id: "run-queued",
      status: "queued",
      product_name: "Áo thun queued",
      latest_narration: null,
      running_seconds_elapsed: 0,
    });
    fetchMock.mockResolvedValue(mockRunsResponse([queued]));

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText("Áo thun queued")).toBeInTheDocument();
    });
    const runningSection = screen.getByRole("heading", { level: 2, name: "Đang chạy" }).closest("section");
    expect(runningSection).not.toBeNull();
    expect(within(runningSection as HTMLElement).getByText("Áo thun queued")).toBeInTheDocument();
  });

  it("labels each of the seven terminal states distinctly, keyed off stop_reason — never a generic 'done'", async () => {
    const finishedRuns: WorkflowRunListItem[] = [
      buildRun({ id: "f-completed", status: "completed", stop_reason: "final_response", product_name: "SP hoàn tất" }),
      buildRun({ id: "f-declined", status: "completed", stop_reason: "confirmation_declined", product_name: "SP từ chối" }),
      buildRun({ id: "f-cancelled", status: "cancelled", stop_reason: "cancelled_by_seller", product_name: "SP huỷ" }),
      buildRun({ id: "f-expired", status: "cancelled", stop_reason: "confirmation_expired", product_name: "SP hết hạn" }),
      buildRun({ id: "f-timedout", status: "timed_out", stop_reason: "wall_clock_timeout", product_name: "SP quá giờ" }),
      buildRun({ id: "f-failed", status: "failed", stop_reason: "tool_error_unrecoverable", product_name: "SP thất bại" }),
      buildRun({ id: "f-workerlost", status: "failed", stop_reason: "worker_lost", product_name: "SP sự cố" }),
    ];
    fetchMock.mockResolvedValue(mockRunsResponse(finishedRuns));

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText("SP hoàn tất")).toBeInTheDocument();
    });

    const labels = [
      RUN_TERMINAL_STATE_COPY.completed.label,
      RUN_TERMINAL_STATE_COPY.completed_after_decline.label,
      RUN_TERMINAL_STATE_COPY.cancelled.label,
      RUN_TERMINAL_STATE_COPY.expired.label,
      RUN_TERMINAL_STATE_COPY.timed_out.label,
      RUN_TERMINAL_STATE_COPY.failed.label,
      RUN_TERMINAL_STATE_COPY.worker_lost.label,
    ];

    // All seven distinct
    expect(new Set(labels).size).toBe(7);

    for (const label of labels) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });

  it("never renders a retry-in-place control anywhere on the surface", async () => {
    const finishedRuns: WorkflowRunListItem[] = [
      buildRun({ id: "f-failed", status: "failed", stop_reason: "tool_error_unrecoverable", product_name: "SP thất bại" }),
      buildRun({ id: "f-workerlost", status: "failed", stop_reason: "worker_lost", product_name: "SP sự cố" }),
      buildRun({ id: "f-timedout", status: "timed_out", stop_reason: "wall_clock_timeout", product_name: "SP quá giờ" }),
    ];
    fetchMock.mockResolvedValue(mockRunsResponse(finishedRuns));

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText("SP thất bại")).toBeInTheDocument();
    });

    const RETRY_PATTERN = /thử lại|chạy lại|làm lại|retry|run again|re-?run/i;

    const interactiveNodes = [
      ...screen.queryAllByRole("button"),
      ...screen.queryAllByRole("link"),
    ];
    for (const node of interactiveNodes) {
      expect(node.textContent ?? "").not.toMatch(RETRY_PATTERN);
      expect(node.getAttribute("aria-label") ?? "").not.toMatch(RETRY_PATTERN);
    }
    expect(document.body.textContent ?? "").not.toMatch(RETRY_PATTERN);
  });

  it("points a failed run's card back to Decisions with the no-new-run-without-approval explanation", async () => {
    const failed = buildRun({ id: "f-failed", status: "failed", stop_reason: "tool_error_unrecoverable", product_name: "SP thất bại" });
    fetchMock.mockResolvedValue(mockRunsResponse([failed]));

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText("SP thất bại")).toBeInTheDocument();
    });

    expect(
      screen.getByText(
        "Muốn thực hiện thay đổi mới? Hãy quay lại Quyết định để phê duyệt đề xuất mới.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Về Quyết định" })).toHaveAttribute(
      "href",
      "/decisions",
    );
  });

  it("links every card to the per-run route by run id — the entry point into the frozen replay view", async () => {
    const finished = buildRun({ id: "run-abc-123", status: "completed", stop_reason: "final_response", product_name: "SP finished" });
    fetchMock.mockResolvedValue(mockRunsResponse([finished]));

    renderPanel();

    await waitFor(() => {
      expect(screen.getByRole("link", { name: "SP finished" })).toHaveAttribute(
        "href",
        "/decisions/in-progress/run-abc-123",
      );
    });
  });

  it("shows the expiry countdown for a waiting_approval run, computed from decision_summary.expires_at on a fixed clock", async () => {
    vi.setSystemTime(new Date("2026-08-25T10:00:00.000Z"));

    const waiting = buildRun({
      id: "run-waiting",
      status: "waiting_approval",
      product_name: "SP waiting",
      decision_summary: { tool_call_id: "call-1", expires_at: "2026-08-25T13:58:00.000Z" },
    });
    fetchMock.mockResolvedValue(mockRunsResponse([waiting]));

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText("Đề xuất còn hiệu lực 3 giờ 58 phút")).toBeInTheDocument();
    });
  });

  it("carries the panelId prop through to the root element id, for aria-controls composition", async () => {
    render(
      <DemoStateProvider>
        <InProgressPanel panelId="custom-panel-id" />
      </DemoStateProvider>,
    );

    await waitFor(() => {
      expect(document.getElementById("custom-panel-id")).toBeInTheDocument();
    });
  });

  it("renders under the scoped run-surface visual identity, not app-wide ordinary emphasis", async () => {
    renderPanel();

    await waitFor(() => {
      const root = document.getElementById("in-progress-panel");
      expect(root).toHaveAttribute("data-juli-surface", "run");
    });
  });

  it("never leaks raw internal status/stop_reason vocabulary to the seller", async () => {
    const finished = buildRun({ id: "f1", status: "failed", stop_reason: "tool_error_unrecoverable", product_name: "SP1" });
    fetchMock.mockResolvedValue(mockRunsResponse([finished]));

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText("SP1")).toBeInTheDocument();
    });

    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/waiting_approval|tool_error_unrecoverable|stop_reason/i);
  });

  it("shows the In Progress tab placeholder through RecommendationsView when no runs exist", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();

    render(
      <DemoStateProvider>
        <RecommendationsView />
      </DemoStateProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Đang thực hiện" }));

    await waitFor(() => {
      expect(
        screen.getByText("Chưa có quyết định nào đang thực hiện."),
      ).toBeInTheDocument();
    });
  });

  it("cards are reachable in section priority order — waiting, then running, then finished", async () => {
    const waiting = buildRun({ id: "run-a-waiting", status: "waiting_approval", product_name: "A" });
    const running = buildRun({ id: "run-b-running", status: "running", product_name: "B" });
    const finished = buildRun({ id: "run-c-finished", status: "completed", stop_reason: "final_response", product_name: "C" });

    // Deliberately fed out of priority order — the ledger must still
    // render them in section priority order, never the server's raw order.
    fetchMock.mockResolvedValue(mockRunsResponse([finished, running, waiting]));

    renderPanel();

    await waitFor(() => {
      expect(document.querySelectorAll("[data-run-card-id]")).toHaveLength(3);
    });

    const orderedIds = Array.from(document.querySelectorAll("[data-run-card-id]")).map((el) =>
      el.getAttribute("data-run-card-id"),
    );
    expect(orderedIds).toEqual(["run-a-waiting", "run-b-running", "run-c-finished"]);
  });

  it("uses the reduced-motion timing for the running card's breathing indicator when the seller prefers reduced motion", async () => {
    const matchMediaMock = vi.fn().mockReturnValue({
      matches: true,
      media: "",
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
      onchange: null,
    });
    vi.stubGlobal("matchMedia", matchMediaMock);

    const running = buildRun({ id: "run-reduced", status: "running", product_name: "SP reduced" });
    fetchMock.mockResolvedValue(mockRunsResponse([running]));

    renderPanel();

    await waitFor(() => {
      expect(screen.getByTestId("run-ledger-breathing-dot")).toBeInTheDocument();
    });

    const dot = screen.getByTestId("run-ledger-breathing-dot");
    // Thinking-state reduced-motion timing (RUN_SURFACE_MOTION_TABLE): 0ms.
    expect(dot.style.animationDuration).toBe("0ms");
  });

  it("uses the full motion timing for the breathing indicator when reduced motion is not requested", async () => {
    const running = buildRun({ id: "run-full-motion", status: "running", product_name: "SP full motion" });
    fetchMock.mockResolvedValue(mockRunsResponse([running]));

    renderPanel();

    await waitFor(() => {
      expect(screen.getByTestId("run-ledger-breathing-dot")).toBeInTheDocument();
    });

    const dot = screen.getByTestId("run-ledger-breathing-dot");
    // Thinking-state full-motion timing (RUN_SURFACE_MOTION_TABLE): 1600ms.
    expect(dot.style.animationDuration).toBe("1600ms");
  });

  it("does not put the expiry countdown in a live region that would announce every second", async () => {
    const waiting = buildRun({
      id: "run-waiting-a11y",
      status: "waiting_approval",
      product_name: "SP a11y waiting",
      decision_summary: { tool_call_id: "call-1", expires_at: "2026-08-25T13:58:00.000Z" },
    });
    fetchMock.mockResolvedValue(mockRunsResponse([waiting]));

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText("SP a11y waiting")).toBeInTheDocument();
    });

    const expiryNode = document.querySelector(".run-ledger__expiry");
    expect(expiryNode).not.toBeNull();
    expect(expiryNode?.getAttribute("aria-live")).toBeNull();
    expect(expiryNode?.closest("[aria-live]")).toBeNull();
  });

  it("uses real section headings as landmarks (h2 + aria-labelledby), not decorative text", async () => {
    const waiting = buildRun({ id: "run-heading", status: "waiting_approval", product_name: "SP heading" });
    fetchMock.mockResolvedValue(mockRunsResponse([waiting]));

    renderPanel();

    await waitFor(() => {
      const heading = screen.getByRole("heading", { level: 2, name: "Đang chờ bạn" });
      const section = heading.closest("section");
      expect(section).not.toBeNull();
      expect(section?.getAttribute("aria-labelledby")).toBe(heading.id);
    });
  });
});
