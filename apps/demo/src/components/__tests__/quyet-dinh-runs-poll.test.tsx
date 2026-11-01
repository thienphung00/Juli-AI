import type { WorkflowRunListItem } from "@juli/contracts";
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RUN_LEDGER_POLL_INTERVAL_MS } from "../../lib/run-ledger/panel-config";
import { REAL_QD_CLIENTS, SignedInQuyetDinh, type QdClients } from "../quyet-dinh/signed-in-quyet-dinh";

/**
 * P82 (Supabase egress): the runs list is polled every 15 s, only while the tab is
 * visible and a run in the list is still live; showing the tab again re-reads at once.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

function run(id: string, status: string): WorkflowRunListItem {
  return {
    id,
    status,
    stop_reason: status === "completed" ? "final_response" : null,
    product_name: "Son môi số 12",
    created_at: "2026-10-09T03:00:00Z",
    completed_at: null,
    running_seconds_elapsed: 0,
    latest_narration: null,
    decision_summary: null,
  } as WorkflowRunListItem;
}

const emptyStream = vi.fn(
  async () => new Response("", { status: 200, headers: { "Content-Type": "text/event-stream" } }),
) as unknown as typeof fetch;

function clients(fetchRuns: QdClients["fetchRuns"]): QdClients {
  return {
    ...REAL_QD_CLIENTS,
    fetchDecisions: vi.fn().mockResolvedValue([]),
    fetchRuns,
    fetchRules: vi.fn().mockRejectedValue(new Error("not in this test")),
    fetchChanges: vi.fn().mockRejectedValue(new Error("not in this test")),
    fetchQuestions: vi.fn().mockResolvedValue([]),
    fetchMeasurement: vi.fn().mockResolvedValue(null),
    fetchRunDetail: vi.fn().mockResolvedValue(null),
    streamFetch: emptyStream,
  };
}

function show(c: QdClients) {
  render(
    <SignedInQuyetDinh
      clients={c}
      onNavigate={vi.fn()}
      query={{ tab: "dang-thuc-hien", run: null, rulesOpen: false }}
      shop={{ id: "shop-1", name: "Shop" }}
      token="tok"
    />,
  );
}

let hidden = false;

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

async function setHidden(value: boolean) {
  hidden = value;
  await act(async () => {
    document.dispatchEvent(new Event("visibilitychange"));
    await Promise.resolve();
  });
}

beforeEach(() => {
  hidden = false;
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("runs list polling (P82)", () => {
  it("polls every 15 s while a run is live", async () => {
    expect(RUN_LEDGER_POLL_INTERVAL_MS).toBe(15_000);
    const fetchRuns = vi.fn().mockResolvedValue([run("r1", "running")]);
    show(clients(fetchRuns));
    await advance(100);
    expect(fetchRuns).toHaveBeenCalledTimes(1);
    await advance(5_000);
    expect(fetchRuns).toHaveBeenCalledTimes(1);
    await advance(10_000);
    expect(fetchRuns).toHaveBeenCalledTimes(2);
  });

  it("stops polling when every run in the list has ended", async () => {
    const fetchRuns = vi.fn().mockResolvedValue([run("r1", "completed"), run("r2", "failed")]);
    show(clients(fetchRuns));
    await advance(100);
    await advance(60_000);
    expect(fetchRuns).toHaveBeenCalledTimes(1);
  });

  it("pauses while the tab is hidden and re-reads at once when it is shown", async () => {
    const fetchRuns = vi.fn().mockResolvedValue([run("r1", "waiting_external")]);
    show(clients(fetchRuns));
    await advance(100);
    expect(fetchRuns).toHaveBeenCalledTimes(1);
    await setHidden(true);
    await advance(60_000);
    expect(fetchRuns).toHaveBeenCalledTimes(1);
    await setHidden(false);
    await advance(10);
    expect(fetchRuns).toHaveBeenCalledTimes(2);
    await advance(15_000);
    expect(fetchRuns).toHaveBeenCalledTimes(3);
  });

  it("an all-ended list is still re-read when the tab is shown again", async () => {
    const fetchRuns = vi.fn().mockResolvedValue([run("r1", "completed")]);
    show(clients(fetchRuns));
    await advance(100);
    await setHidden(true);
    await setHidden(false);
    await advance(10);
    expect(fetchRuns).toHaveBeenCalledTimes(2);
  });
});
