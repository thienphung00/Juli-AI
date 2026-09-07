/**
 * Proves the shared `[executionId]` route dispatches correctly between the
 * legacy mock detail view (untouched, #1318/#1320's mock layer) and #1316's
 * staged run view, based on the id's shape alone -- no network call is
 * needed to make that decision, which is exactly why the pinned "unknown
 * executionId" behavior in `in-progress-detail-view.test.tsx` (a non-UUID
 * mock id) is untouched by this addition.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DemoStateProvider } from "../components/demo-state";
import { InProgressDetailView } from "../app/decisions/in-progress/[executionId]/page";

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

function mockFetch(data: unknown) {
  return vi.spyOn(global, "fetch").mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ success: true, data }),
  } as Response);
}

function renderRoute(executionId: string) {
  return render(
    <DemoStateProvider>
      <InProgressDetailView executionId={executionId} />
    </DemoStateProvider>,
  );
}

describe("the shared [executionId] route dispatches by id shape", () => {
  it("renders the staged run view for a UUID-shaped id not present in mock records", async () => {
    const fetchSpy = mockFetch([
      {
        id: RUN_ID,
        status: "waiting_approval",
        stop_reason: null,
        product_name: "Áo thun cotton nam",
        created_at: "2026-08-28T08:00:00.000Z",
        completed_at: null,
        running_seconds_elapsed: 12,
        latest_narration: null,
        decision_summary: null,
      },
    ]);

    renderRoute(RUN_ID);

    await waitFor(() => {
      expect(screen.getByRole("tablist")).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("status", { name: "Không tìm thấy luồng thực hiện" }),
    ).not.toBeInTheDocument();

    fetchSpy.mockRestore();
  });

  it("still shows the legacy not-found state for a non-UUID unknown id (unchanged)", () => {
    renderRoute("exec-does-not-exist");

    expect(
      screen.getByRole("status", { name: "Không tìm thấy luồng thực hiện" }),
    ).toHaveTextContent("Không tìm thấy luồng thực hiện");
  });
});
