import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { WorkflowRunListItem } from "@juli/contracts";

import { RunDetailRoute } from "../run-detail-route";

vi.mock("next/navigation", () => ({
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => "/decisions/in-progress/run-1"),
  useRouter: vi.fn(() => ({
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
    push: vi.fn(),
    refresh: vi.fn(),
    replace: vi.fn(),
  })),
}));

const RUN_ID = "6fed3803-a77e-4d55-9ea3-ac72d25e77e2";

function buildRun(overrides: Partial<WorkflowRunListItem> = {}): WorkflowRunListItem {
  return {
    id: RUN_ID,
    status: "waiting_approval",
    stop_reason: null,
    product_name: "Áo thun cotton nam",
    created_at: "2026-08-28T08:00:00.000Z",
    completed_at: null,
    running_seconds_elapsed: 12,
    latest_narration: null,
    decision_summary: null,
    ...overrides,
  };
}

describe("RunDetailRoute", () => {
  it("shows a loading state, then the staged view once the run is found", async () => {
    const fetchRuns = vi.fn().mockResolvedValue([buildRun()]);

    render(<RunDetailRoute fetchRuns={fetchRuns} runId={RUN_ID} />);

    expect(screen.getByRole("status")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByRole("tablist")).toBeInTheDocument();
    });
    expect(fetchRuns).toHaveBeenCalledTimes(1);
  });

  it("shows the honest not-found recovery state for a run id the list does not contain", async () => {
    const fetchRuns = vi.fn().mockResolvedValue([]);

    render(<RunDetailRoute fetchRuns={fetchRuns} runId={RUN_ID} />);

    await waitFor(() => {
      expect(
        screen.getByRole("status", { name: "Không tìm thấy luồng thực hiện" }),
      ).toBeInTheDocument();
    });
    expect(screen.getByRole("link", { name: "Về Quyết định" })).toHaveAttribute(
      "href",
      "/decisions",
    );
  });

  it("shows the honest not-found recovery state when the list fetch fails", async () => {
    const fetchRuns = vi.fn().mockRejectedValue(new Error("network down"));

    render(<RunDetailRoute fetchRuns={fetchRuns} runId={RUN_ID} />);

    await waitFor(() => {
      expect(
        screen.getByRole("status", { name: "Không tìm thấy luồng thực hiện" }),
      ).toBeInTheDocument();
    });
  });
});
