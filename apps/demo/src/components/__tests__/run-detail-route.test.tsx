import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { WorkflowRunListItem } from "@juli/contracts";

import { RunDetailRoute } from "../run-detail-route";
import { InProgressDetailView } from "../../app/decisions/in-progress/[executionId]/page";
import { DemoStateProvider } from "../demo-state";
import { DEMO_RUNS_API_PATH } from "../../lib/run-ledger/api-client";
import { REPLAY_SCENARIO_RUN_ID } from "../../lib/run-surface/replay-scenario";
import { storeActiveShop } from "../../lib/shop-session";
import { storeAuthSession } from "../../lib/supabase-auth";

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

// The captured run's own id, not a copy of it — #1862 re-captured the
// scenario deterministically and every restated literal went stale.
const RUN_ID = REPLAY_SCENARIO_RUN_ID;
const TOKEN = "test-bearer-token";

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

describe("RunDetailRoute — signed-in path (a token is present)", () => {
  it("leaves the signed-in path unchanged: with a token it still connects to the real run endpoint, never the seeded scenario", async () => {
    const fetchRuns = vi.fn().mockResolvedValue([buildRun()]);

    render(<RunDetailRoute fetchRuns={fetchRuns} runId={RUN_ID} token={TOKEN} />);

    expect(screen.getByRole("status")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByRole("tablist")).toBeInTheDocument();
    });
    expect(fetchRuns).toHaveBeenCalledTimes(1);
  });

  it("shows the honest not-found recovery state for a run id the list does not contain", async () => {
    const fetchRuns = vi.fn().mockResolvedValue([]);

    render(<RunDetailRoute fetchRuns={fetchRuns} runId={RUN_ID} token={TOKEN} />);

    await waitFor(() => {
      expect(
        screen.getByRole("status", { name: "Không tìm thấy luồng thực hiện" }),
      ).toBeInTheDocument();
    });
    expect(screen.getByRole("link", { name: "Về Hành động" })).toHaveAttribute(
      "href",
      "/decisions",
    );
  });

  it("shows the honest not-found recovery state when the list fetch fails", async () => {
    const fetchRuns = vi.fn().mockRejectedValue(new Error("network down"));

    render(<RunDetailRoute fetchRuns={fetchRuns} runId={RUN_ID} token={TOKEN} />);

    await waitFor(() => {
      expect(
        screen.getByRole("status", { name: "Không tìm thấy luồng thực hiện" }),
      ).toBeInTheDocument();
    });
  });
});

describe("RunDetailRoute — the signed-in lookup carries the session's credentials (#1909)", () => {
  it("passes the bearer token and the acting shop's id to fetchRuns", async () => {
    const fetchRuns = vi.fn().mockResolvedValue([buildRun()]);

    render(
      <RunDetailRoute
        fetchRuns={fetchRuns}
        runId={RUN_ID}
        shopId="shop-1"
        token={TOKEN}
      />,
    );

    await waitFor(() => {
      expect(fetchRuns).toHaveBeenCalledTimes(1);
    });
    expect(fetchRuns.mock.calls[0][0]).toMatchObject({
      token: TOKEN,
      shopId: "shop-1",
    });
  });
});

describe("the [executionId] page door — a stored auth session selects the signed-in door (#1909)", () => {
  function renderPage(runId: string) {
    return render(
      <DemoStateProvider>
        <InProgressDetailView executionId={runId} />
      </DemoStateProvider>,
    );
  }

  it("with a stored auth session, the signed-in door renders and the run lookup is issued with its credentials", async () => {
    storeAuthSession({
      accessToken: TOKEN,
      refreshToken: null,
      expiresIn: 3600,
      tokenType: "bearer",
    });
    storeActiveShop({ id: "shop-1", name: "Shop Minh Anh" });
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [buildRun()] }),
    } as Response);

    try {
      renderPage(RUN_ID);

      await waitFor(() => {
        const lookupCalls = fetchSpy.mock.calls.filter(
          ([input]) => String(input) === DEMO_RUNS_API_PATH,
        );
        expect(lookupCalls).toHaveLength(1);
      });

      const [, init] = fetchSpy.mock.calls.find(
        ([input]) => String(input) === DEMO_RUNS_API_PATH,
      ) as [string, RequestInit];
      const headers = new Headers(init.headers);
      expect(headers.get("Authorization")).toBe(`Bearer ${TOKEN}`);
      expect(headers.get("X-Shop-Id")).toBe("shop-1");
    } finally {
      window.sessionStorage.clear();
      fetchSpy.mockRestore();
    }
  });

  it("without a stored session, the replay door renders and the run lookup is never issued", async () => {
    window.sessionStorage.clear();
    const fetchSpy = vi.spyOn(global, "fetch");

    try {
      renderPage(REPLAY_SCENARIO_RUN_ID);

      await waitFor(() => {
        expect(screen.getByRole("tablist")).toBeInTheDocument();
      });
      expect(fetchSpy).not.toHaveBeenCalled();
    } finally {
      fetchSpy.mockRestore();
    }
  });
});

describe("RunDetailRoute — replay path (no token, issue #1752)", () => {
  it("seeds the staged view from the captured scenario with zero /v1/* requests", async () => {
    const fetchRuns = vi.fn();
    const fetchSpy = vi.spyOn(global, "fetch");

    render(<RunDetailRoute fetchRuns={fetchRuns} runId={REPLAY_SCENARIO_RUN_ID} />);

    await waitFor(() => {
      expect(screen.getByRole("tablist")).toBeInTheDocument();
    });

    // No lookup call (the signed-in-only client) and no raw fetch at all
    // (the structural bar #1319 already enforces over the module graph,
    // reasserted here at the component boundary).
    expect(fetchRuns).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();

    fetchSpy.mockRestore();
  });

  it("shows the honest not-found state, with zero network, for an id that is not the replay scenario", () => {
    const fetchRuns = vi.fn();
    const fetchSpy = vi.spyOn(global, "fetch");

    render(<RunDetailRoute fetchRuns={fetchRuns} runId="not-the-replay-run" />);

    expect(
      screen.getByRole("status", { name: "Không tìm thấy luồng thực hiện" }),
    ).toBeInTheDocument();
    expect(fetchRuns).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();

    fetchSpy.mockRestore();
  });

  // Issue #1764: before this fix, `ReplayRunDetail` rendered `RunStagedView`
  // with no `confirm` override, so clicking either control here fell
  // through to `OptionPicker`'s old default, `submitConfirmationDecision`
  // -- a real, bearer-less POST to the confirmation route, observed
  // 404ing. Both tests below drive the actual click and assert zero
  // network for the whole journey, then assert the run actually reaches a
  // terminal state (the decision was genuinely resolved, not silently
  // swallowed).
  it("confirming an option resolves the decision locally -- zero network, and the run reaches a terminal state", async () => {
    const fetchRuns = vi.fn();
    const fetchSpy = vi.spyOn(global, "fetch");
    const user = userEvent.setup();

    render(<RunDetailRoute fetchRuns={fetchRuns} runId={REPLAY_SCENARIO_RUN_ID} />);

    await waitFor(() => {
      expect(screen.getByRole("radio")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("radio"));
    await user.click(screen.getByRole("button", { name: "Xác nhận phương án này" }));

    await waitFor(() => {
      expect(screen.getByText("Hoàn tất")).toBeInTheDocument();
    });

    expect(fetchRuns).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();

    fetchSpy.mockRestore();
  });

  it("declining resolves the decision locally -- zero network, and the run reaches its declined terminal state", async () => {
    const fetchRuns = vi.fn();
    const fetchSpy = vi.spyOn(global, "fetch");
    const user = userEvent.setup();

    render(<RunDetailRoute fetchRuns={fetchRuns} runId={REPLAY_SCENARIO_RUN_ID} />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Không thực hiện" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Không thực hiện" }));

    await waitFor(() => {
      // Since #1910 the declined label renders on TWO honest surfaces: the
      // run header's status chip and the Hoàn tất stage card -- at least
      // one occurrence is the assertion (same idiom as the §3 title check
      // in run-staged-view.test.tsx).
      expect(screen.getAllByText("Hoàn tất — không đổi").length).toBeGreaterThan(0);
    });

    expect(fetchRuns).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();

    fetchSpy.mockRestore();
  });
});
