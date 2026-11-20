import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SyncStatusLine } from "../app-shell/sync-status-line";
import { SYNC_STATUS_API_PATH, syncStatusLine, type SyncStatus } from "../../lib/sync-status/api-client";

/** P101 W2 B-5: one status line — backfill progress, then "Số liệu đến dd/mm". */

const BASE: SyncStatus = {
  state: "active",
  backfilling: false,
  history_days_done: 90,
  history_days_total: 90,
  data_through: "2026-11-19",
  late: false,
};

function fetchOf(payload: unknown, status = 200) {
  return vi.fn(async () => new Response(JSON.stringify(payload), { status })) as unknown as typeof fetch;
}

afterEach(() => cleanup());

describe("syncStatusLine", () => {
  it("names the 90-day backfill with n/90 while it runs", () => {
    expect(syncStatusLine({ ...BASE, state: "backfilling", backfilling: true, history_days_done: 37 })).toBe(
      "Đang tải dữ liệu 90 ngày · 37/90",
    );
  });

  it("shows the data-through date as dd/mm once the backfill is done", () => {
    expect(syncStatusLine(BASE)).toBe("Số liệu đến 19/11");
    expect(syncStatusLine({ ...BASE, state: "degraded", late: true, data_through: "2026-11-18" })).toBe("Số liệu đến 18/11");
  });

  it("says nothing without a date, when disconnected or when the seller must re-authorise", () => {
    expect(syncStatusLine({ ...BASE, data_through: null })).toBeNull();
    expect(syncStatusLine({ ...BASE, state: "disconnected" })).toBeNull();
    expect(syncStatusLine({ ...BASE, state: "needs_reauth" })).toBeNull();
  });
});

describe("SyncStatusLine", () => {
  it("reads the route with bearer and X-Shop-Id and renders only the line", async () => {
    const fetchImpl = fetchOf({ ...BASE, state: "backfilling", backfilling: true, history_days_done: 12 });
    render(<SyncStatusLine fetchImpl={fetchImpl} pollMs={1_000_000} shopId="shop-1" token="t" />);
    const line = await screen.findByTestId("sync-status-line");
    expect(line.textContent).toBe("Đang tải dữ liệu 90 ngày · 12/90");
    const [url, init] = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toBe(SYNC_STATUS_API_PATH);
    expect(init.headers).toMatchObject({ Authorization: "Bearer t", "X-Shop-Id": "shop-1" });
  });

  it("shows Số liệu đến dd/mm when no backfill runs", async () => {
    render(<SyncStatusLine fetchImpl={fetchOf(BASE)} shopId="shop-1" token="t" />);
    expect((await screen.findByTestId("sync-status-line")).textContent).toBe("Số liệu đến 19/11");
  });

  it("re-reads the progress while the backfill runs", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...BASE, state: "backfilling", backfilling: true, history_days_done: 10 })))
      .mockResolvedValue(new Response(JSON.stringify(BASE)));
    render(<SyncStatusLine fetchImpl={fetchImpl as unknown as typeof fetch} pollMs={5} shopId="shop-1" token="t" />);
    await waitFor(() => expect(screen.getByTestId("sync-status-line").textContent).toBe("Số liệu đến 19/11"));
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("renders nothing for a refused call", async () => {
    const fetchImpl = fetchOf({ detail: "no" }, 401);
    const { container } = render(<SyncStatusLine fetchImpl={fetchImpl} shopId="shop-1" token="t" />);
    await waitFor(() => expect(fetchImpl).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });
});
