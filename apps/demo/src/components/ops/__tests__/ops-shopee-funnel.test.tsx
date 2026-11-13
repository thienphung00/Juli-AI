import { render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OpsShopeeFunnel, byDay, type CoverageFamily, type FunnelApi, type FunnelCheck, type FunnelMismatch } from "../shopee/ops-shopee-funnel";
import { ME, SHOP_ID } from "./fixtures";

/** P98 d.11.3-d.11.4: the Lệch số liệu page. Synthetic numbers only. */

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("../ops-cost-banner", () => ({ OpsCostBanner: () => null }));

const mm = (o: Partial<FunnelMismatch>): FunnelMismatch => ({ kind: "shop_totals", day: "2026-11-08", scope: "shop", item_id: null, source: null, metric: "gmv", expected: "1000000", actual: "900000", gap_pct: 10, ...o });
const check = (mismatches: FunnelMismatch[]): FunnelCheck => ({ days: 14, from: "2026-10-26", to: "2026-11-08", tolerance_pct: 1, mismatches });
const family = (o: Partial<CoverageFamily>): CoverageFamily => ({ family: "voucher", scored: 10, inside: 8, coverage: 0.8, metrics: [], ...o });

function api(c: FunnelCheck, families: CoverageFamily[] = []): FunnelApi {
  return {
    funnelCheck: vi.fn(async () => c),
    predictionCoverage: vi.fn(async () => ({ target: 0.8, source: "shopee_reco_calibrations", families })),
  };
}

describe("OpsShopeeFunnel", () => {
  it("shows one table per day with the Vietnamese kind labels", async () => {
    const rows = [
      mm({ kind: "missing_rows", metric: "rows", expected: null, actual: "0", gap_pct: null }),
      mm({ kind: "sources_sum", day: "2026-11-07", metric: "orders", item_id: "1001", scope: "product", expected: "4", actual: "3", gap_pct: 25 }),
      mm({ kind: "traffic", day: "2026-11-07", metric: "views", source: "video", expected: "100", actual: "90" }),
      mm({ kind: "shop_totals" }),
    ];
    render(<OpsShopeeFunnel api={api(check(rows))} me={ME} shopId={SHOP_ID} />);
    const day8 = await screen.findByRole("table", { name: "Lệch số liệu ngày 08/11/2026" });
    const day7 = screen.getByRole("table", { name: "Lệch số liệu ngày 07/11/2026" });
    expect(within(day8).getByText("Thiếu dòng nguồn")).toBeTruthy();
    expect(within(day8).getByText("Lệch tổng shop của Shopee")).toBeTruthy();
    expect(within(day7).getByText("Tổng các nguồn không khớp")).toBeTruthy();
    expect(within(day7).getByText("Lệch lượt xem / lượt nhấp")).toBeTruthy();
    expect(within(day7).getByText("Sản phẩm 1001")).toBeTruthy();
    expect(within(day7).getByText("25 %")).toBeTruthy();
    expect(screen.queryByText("Không có lệch số liệu")).toBeNull();
  });

  it("says so when nothing is off", async () => {
    render(<OpsShopeeFunnel api={api(check([]))} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByText("Không có lệch số liệu")).toBeTruthy();
  });

  it("lists coverage per family against the 80 % target, never 0 % for nothing scored", async () => {
    const fams = [family({}), family({ family: "price", scored: 0, inside: 0, coverage: null }), family({ family: "ads", scored: 10, inside: 5, coverage: 0.5 })];
    render(<OpsShopeeFunnel api={api(check([]), fams)} me={ME} shopId={SHOP_ID} />);
    const table = await screen.findByRole("table", { name: "Độ phủ theo nhóm" });
    expect(within(table).getByText("80 %")).toBeTruthy();
    expect(within(table).getByText("50 %")).toBeTruthy();
    expect(within(table).getByText("chưa có kết quả")).toBeTruthy();
    expect(screen.getByText(/mục tiêu khoảng 80 %/)).toBeTruthy();
  });

  it("names a refused read instead of an empty table", async () => {
    const failing: FunnelApi = { funnelCheck: vi.fn(async () => { throw Object.assign(new Error("x"), { status: 409 }); }), predictionCoverage: vi.fn(async () => ({ target: 0.8, source: "s", families: [] })) };
    render(<OpsShopeeFunnel api={failing} me={ME} shopId={SHOP_ID} />);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("không phải shop Shopee"));
  });

  it("groups by day, newest first", () => {
    expect(byDay([mm({ day: "2026-11-06" }), mm({ day: "2026-11-08" }), mm({ day: "2026-11-06", metric: "orders" })]).map(([d, r]) => [d, r.length])).toEqual([["2026-11-08", 1], ["2026-11-06", 2]]);
  });
});
