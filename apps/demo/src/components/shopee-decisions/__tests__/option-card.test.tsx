import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BuilderOutcome } from "../../../lib/shopee-decisions/builder-api";
import type { FunnelColumn, OptionResult } from "../../../lib/shopee-decisions/option-result";
import { CompareTable, OptionCard } from "../option-card";
import { SOURCE_LABELS } from "../option-card/option-card";
import { OutcomeBody } from "../builder-p92/results";

const col = (over: Partial<FunnelColumn> = {}): FunnelColumn => ({ views: 10000, ctr: 3.5, ctor: 4.2, orders: 100, aov: 200000, gmv: 20000000, profit: 3000000, by_source: { trang_shop: { orders: 60, gmv: 12000000 }, the_san_pham_khac: { orders: 20, gmv: 4000000 } }, ...over });

function result(over: Partial<OptionResult> = {}): OptionResult {
  return {
    kind: "price_change",
    label: "Giảm giá 5%",
    days: 7,
    horizon: "duration",
    drivers: ["ctor", "aov"],
    estimable: true,
    basis: "product_history",
    basis_weak: false,
    delta: {
      profit: { value: 1234567, pct: 5.5, low: 500000, high: 2000000 },
      gmv: { value: 2500000, pct: 12.5 },
      orders: { value: 12, pct: 12, note: null },
    },
    build_up: [{ key: "a", amount: 1, text: "+300.000đ từ đơn thêm." }, { key: "b", amount: 2, text: "−50.000đ giảm giá." }],
    drivers_pct: [
      { metric: "aov", label: "AOV", pct: 1.7 },
      { metric: "ctor", label: "CTOR", pct: 1.8 },
    ],
    cost: { total: 150000, break_even_orders: 5, break_even_aov: null, text: "Chi phí 150.000đ · hoà vốn khi thêm ≥ 5 đơn" },
    after: { days: 7, label: "Sau 7 ngày", gmv_before: 20000000, gmv_after: 22500000, profit_before: 3000000, profit_after: 4234567 },
    per_30d: { profit: 5000000, gmv: 10000000, orders: 50 },
    roi: { value: 2500000 / 150000, text: "ROI 16,7" },
    margin: { before_pct: 15, after_pct: 18.82, shift_pts: 3.82 },
    detail: { before: col(), low: col({ orders: 105 }), likely: col({ orders: 112, gmv: 22500000, profit: 4234567, views: 10500, ctr: 3.6, ctor: 4.3, aov: 205000 }), high: col({ orders: 120 }) },
    notes: ["Số liệu 28 ngày gần nhất."],
    ...over,
  };
}

describe("P98 W3-I · OptionCard", () => {
  it("shows exactly the d.5 lines, formatted vi-VN", () => {
    render(<OptionCard result={result()} />);
    // F7.8: one dự kiến amount per metric with hiện tại and the change under it; never a range, no Δ-only line
    expect(screen.getByTestId("oc-fc-profit")).toHaveTextContent("Lợi nhuận đóng góp dự kiến (7 ngày): 4.234.567 đ");
    expect(screen.getByTestId("oc-fc-profit-sub")).toHaveTextContent("hiện tại: 3.000.000 đ · +1.234.567 đ (+41,2 %)");
    expect(screen.getByTestId("oc-forecast").textContent).not.toMatch(/…/);
    expect(screen.getByTestId("oc-buildup")).toHaveTextContent("+300.000đ từ đơn thêm. −50.000đ giảm giá.");
    expect(screen.getByTestId("oc-fc-gmv")).toHaveTextContent("GMV dự kiến: 22.500.000 đ");
    expect(screen.getByTestId("oc-fc-gmv-sub")).toHaveTextContent("hiện tại: 20.000.000 đ · +2.500.000 đ (+12,5 %)");
    expect(screen.getByTestId("oc-fc-orders")).toHaveTextContent("Đơn dự kiến: 112 đơn");
    expect(screen.getByTestId("oc-fc-orders-sub")).toHaveTextContent("hiện tại: 100 đơn · +12 (+12,0 %)");
    expect(screen.getByTestId("oc-fc-aov")).toHaveTextContent("AOV dự kiến: 200.893 đ");
    expect(screen.getByTestId("oc-funnel")).toHaveTextContent("Hiển thị 10.000 → 10.500 · CTR 3,50% → 3,60% · CTOR 4,20% → 4,30% · AOV 200.000đ → 205.000đ");
    expect(screen.getByTestId("oc-margin")).toHaveTextContent("15,0% → 18,8% (+3,8 điểm)");
    expect(screen.getByTestId("oc-roi")).toHaveTextContent("16,7");
    expect(screen.getByTestId("oc-cost")).toHaveTextContent("150.000đ");
    expect(screen.getByTestId("oc-cost")).not.toHaveTextContent("hoà vốn");
    expect(screen.getByTestId("oc-breakeven")).toHaveTextContent("cần thêm 5 đơn để hoà vốn");
    expect(screen.queryByTestId("oc-drivers")).toBeNull();
    expect(screen.queryByTestId("oc-after")).toBeNull();
    expect(screen.queryByTestId("oc-per30")).toBeNull();
    expect(screen.queryByTestId("oc-weak")).toBeNull();
    expect(screen.queryByTestId("oc-detail")).toBeNull();
    // F7.8: Dự kiến is the headline; no "Tác động", no "Quy đổi 30 ngày"
    expect(screen.getAllByRole("term").map((t) => t.textContent)).toEqual(["Dự kiến", "Phễu", "Biên đóng góp", "ΔGMV / chi phí", "Chi phí", "Hoà vốn"]);
  });

  it("P100-C: one break-even line with orders or AOV; no ROI / margin without them", () => {
    render(<OptionCard result={result({ cost: { total: 150000, break_even_orders: 5, break_even_aov: 210000, text: "" }, roi: { value: null, text: null }, margin: { before_pct: 15, after_pct: null, shift_pts: null } })} />);
    expect(screen.getByTestId("oc-breakeven")).toHaveTextContent("cần thêm 5 đơn hoặc AOV ≥ 210.000đ để hoà vốn");
    expect(screen.queryByTestId("oc-roi")).toBeNull();
    expect(screen.queryByTestId("oc-margin")).toBeNull();
  });

  it("null profit reads 'chưa ước tính được' with the note; costless-unknown reads 'chưa tính'", () => {
    const note = "Chưa ước tính được.";
    const r = result({ estimable: false, delta: { profit: null, gmv: { value: null, pct: null }, orders: { value: 0, pct: null, note } }, build_up: [], after: { days: 7, label: "Sau 7 ngày", gmv_before: 1, gmv_after: null, profit_before: null, profit_after: null } });
    render(<OptionCard result={r} />);
    expect(screen.getByTestId("oc-fc-profit-value")).toHaveTextContent("—");
    expect(screen.getByTestId("oc-note")).toHaveTextContent(note);
    expect(screen.getByTestId("oc-fc-gmv-value")).toHaveTextContent("—");
    expect(screen.getByTestId("oc-fc-orders-value")).toHaveTextContent("—");
    expect(screen.getByTestId("oc-fc-orders")).not.toHaveTextContent("+0");
    expect(screen.queryByTestId("oc-after")).toBeNull();
  });

  it("'chưa tính' when estimable but profit unknown", () => {
    const r = result();
    render(<OptionCard result={result({ detail: { ...r.detail, likely: { ...r.detail.likely!, profit: null } } })} />);
    expect(screen.getByTestId("oc-fc-profit-value")).toHaveTextContent("—");
    expect(screen.getByTestId("oc-fc-gmv-value")).not.toHaveTextContent("—");
  });

  it("AOV-only: +0 orders and the note", () => {
    const note = "Đòn bẩy này tăng giá trị mỗi đơn, không tăng số đơn.";
    const r = result();
    render(<OptionCard result={result({ drivers: ["aov"], delta: { profit: { value: 100000, pct: 3, low: 50000, high: 150000 }, gmv: { value: 500000, pct: 2 }, orders: { value: 0, pct: 0, note } }, detail: { ...r.detail, likely: { ...r.detail.likely!, orders: 100 } } })} />);
    expect(screen.getByTestId("oc-fc-orders-sub")).toHaveTextContent("hiện tại: 100 đơn · +0 (+0,0 %)");
    expect(screen.getByTestId("oc-note")).toHaveTextContent(note);
  });

  it("shows the 'ước tính chung' tag only when basis_weak; uses '30 ngày đầu' for first_30_days", () => {
    const { rerender } = render(<OptionCard result={result({ basis: "prior", basis_weak: true, horizon: "first_30_days", after: { days: 30, label: "30 ngày đầu", gmv_before: 1, gmv_after: 2, profit_before: 1, profit_after: 2 } })} />);
    expect(screen.getByTestId("oc-weak")).toHaveTextContent("chung");
    expect(screen.getAllByText("30 ngày đầu").length).toBeGreaterThan(0);
    rerender(<OptionCard result={result()} />);
    expect(screen.queryByText("ước tính chung")).toBeNull();
  });

  it("Chi tiết toggles the seven metrics, sources and notes", () => {
    render(<OptionCard result={result()} />);
    fireEvent.click(screen.getByTestId("oc-toggle"));
    const detail = screen.getByTestId("oc-detail");
    for (const k of ["views", "ctr", "ctor", "orders", "aov", "gmv", "profit"]) expect(within(detail).getByTestId(`oc-metric-${k}`)).toBeInTheDocument();
    expect(within(screen.getByTestId("oc-metric-views")).getAllByRole("cell")).toHaveLength(4);
    expect(screen.getByTestId("oc-metric-ctr")).toHaveTextContent("3,50%");
    expect(screen.getByTestId("oc-metric-gmv")).toHaveTextContent("20.000.000đ");
    expect(screen.getByTestId("oc-sources")).toHaveTextContent("60 đơn");
    expect(screen.getByTestId("oc-sources")).toHaveTextContent("Trang shop");
    expect(screen.getByTestId("oc-sources")).toHaveTextContent("Thẻ sản phẩm (ngoài Trang shop)");
    expect(screen.getByTestId("oc-notes")).toHaveTextContent("Số liệu 28 ngày gần nhất.");
    fireEvent.click(screen.getByTestId("oc-toggle"));
    expect(screen.queryByTestId("oc-detail")).toBeNull();
  });
});

describe("P98 W3-I · CompareTable", () => {
  const rows = [
    { id: "a", result: result({ label: "A", per_30d: { profit: 100, gmv: 1, orders: 1 } }) },
    { id: "b", result: result({ label: "B", per_30d: { profit: null, gmv: 1, orders: 1 } }) },
    { id: "c", result: result({ label: "C", per_30d: { profit: 900, gmv: 1, orders: 1 } }) },
    { id: "d", result: result({ label: "D", per_30d: { profit: -50, gmv: 1, orders: 1 } }) },
  ];

  it("keeps the server's order (never re-sorts by per_30d) and captions the server's sort basis", () => {
    render(<CompareTable rows={rows} sortBasis="Δ lợi nhuận mỗi ngày trong các ngày đã đặt" />);
    const body = screen.getByTestId("oc-compare").querySelector("tbody")!;
    expect(within(body).getAllByRole("row").map((r) => r.getAttribute("data-testid"))).toEqual(["oc-row-a", "oc-row-b", "oc-row-c", "oc-row-d"]);
    expect(screen.getByTestId("oc-sort-basis")).toHaveTextContent("Xếp theo: Δ lợi nhuận mỗi ngày trong các ngày đã đặt");
  });

  it("each row carries its own totals in vi-VN", () => {
    render(<CompareTable rows={[rows[0]!]} />);
    const row = screen.getByTestId("oc-row-a");
    expect(row).toHaveTextContent("Sau 7 ngày");
    expect(screen.getByTestId("oc-row-a-profit")).toHaveTextContent("4.234.567 đ");
    expect(screen.getByTestId("oc-row-a-profit-sub")).toHaveTextContent("hiện tại: 3.000.000 đ · +1.234.567 đ (+41,2 %)");
    expect(screen.getByTestId("oc-row-a-gmv")).toHaveTextContent("22.500.000 đ");
    expect(screen.getByTestId("oc-row-a-orders-sub")).toHaveTextContent("hiện tại: 100 đơn · +12 (+12,0 %)");
    expect(screen.getByTestId("oc-row-a-aov")).toHaveTextContent("200.893 đ");
    expect(row).not.toHaveTextContent("Δ");
  });
});

describe("P98 W3-I · builder result block", () => {
  it("draws the card when the outcome has a result", () => {
    const o = { index: 0, kind: "price_change", label: "x", ok: true, result: result() } as unknown as BuilderOutcome;
    render(<OutcomeBody costLink="/x" outcome={o} />);
    expect(screen.getByTestId("option-card")).toBeInTheDocument();
    expect(screen.queryByTestId("p2-dgmv")).toBeNull();
  });
});

describe("P98 W4-C · source labels", () => {
  it("uses the backend source keys", () => {
    expect(SOURCE_LABELS).toEqual({
      the_san_pham_khac: "Thẻ sản phẩm (ngoài Trang shop)",
      trang_shop: "Trang shop",
      live: "Live",
      video: "Video",
      lien_ket: "Liên kết",
      chenh_lech_nguon: "Chênh lệch nguồn",
    });
  });
});

describe("P99 · OptionCard", () => {
  it("break-even and the cost-days note are shown on the card; a not-estimable card keeps its cost", () => {
    const note = "Lợi nhuận mỗi đơn tính trên 20 ngày có dữ liệu chi phí (trong 30 ngày)";
    const r = result({ estimable: false, notes: [note], delta: { profit: null, gmv: { value: 0, pct: 0 }, orders: { value: 0, pct: 0, note: null } } });
    render(<OptionCard result={r} />);
    expect(screen.getByTestId("oc-breakeven")).toHaveTextContent("cần thêm 5 đơn để hoà vốn");
    expect(screen.getByTestId("oc-cost")).toHaveTextContent("150.000đ");
    expect(screen.getByTestId("oc-cost-days")).toHaveTextContent(note);
    expect(screen.getByTestId("oc-fc-orders-value")).toHaveTextContent("—");
    expect(screen.getByTestId("oc-fc-orders")).not.toHaveTextContent("+0");
  });

  it("Đơn dự kiến is whole orders", () => {
    const r = result();
    const withOrders = (n: number) => result({ detail: { ...r.detail, likely: { ...r.detail.likely!, orders: n } } });
    const { rerender } = render(<OptionCard result={withOrders(107.7)} />);
    expect(screen.getByTestId("oc-fc-orders-value")).toHaveTextContent("108 đơn");
    expect(screen.getByTestId("oc-fc-orders-sub")).toHaveTextContent("hiện tại: 100 đơn · +8 (+7,7 %)");
    rerender(<OptionCard result={withOrders(113)} />);
    expect(screen.getByTestId("oc-fc-orders-value")).toHaveTextContent("113 đơn");
  });
});

describe("P100 B.15 · Dịch vụ hiển thị edit on the OptionCard", () => {
  const ads = {
    lever: "budget",
    campaign: "Chiến dịch A",
    days: 30,
    spend_basis: "not_capped",
    spend_text: "Ngân sách mới 80.000đ/ngày thấp hơn mức chiến dịch thực chi (100.000đ/ngày): chi tiêu bằng ngân sách mới.",
    spend: { now: 3000000, after: 2400000 },
    orders: { now: 90, after: 72 },
    cpa: { now: 33333, after: 33333 },
    break_even_cpa: 50000,
    verdict: { now: "co_lai" as const, after: "co_lai" as const },
    verdict_text: { now: "có lãi", after: "có lãi" },
    profit_after_ads: { now: 1500000, after: 1200000 },
    roas_shopee: { now: 6, after: 6 },
    incremental: { share: 50, orders_all: -18, orders_extra: -9 },
    cancel_rate_pct: 10,
  };

  it("shows CPA → CPA mới, CPA hoà vốn, kết luận, lợi nhuận sau quảng cáo and ROAS Shopee", () => {
    render(<OptionCard result={result({ kind: "ads_budget", ads, cost: { total: -600000, break_even_orders: null, break_even_aov: null, text: "Chi phí giảm 600.000đ" } })} />);
    expect(screen.getByTestId("oc-ads-cpa")).toHaveTextContent("33.333đ → 33.333đ");
    expect(screen.getByTestId("oc-ads-be")).toHaveTextContent("50.000đ");
    expect(screen.getByTestId("oc-ads-verdict")).toHaveTextContent("có lãi");
    expect(screen.getByTestId("oc-ads-profit")).toHaveTextContent("1.500.000đ → 1.200.000đ");
    expect(screen.getByTestId("oc-ads-roas")).toHaveTextContent("6,0");
    expect(screen.queryByTestId("oc-ads-spend")).toBeNull();
    expect(screen.queryByTestId("oc-ads-incremental")).toBeNull();
    expect(screen.queryByTestId("oc-ads-cancel")).toBeNull();
    expect(screen.getByTestId("oc-cost")).toHaveTextContent("Giảm 600.000đ");
  });

  it("says chưa ước tính được when the edit has no history, and loses money as lỗ", () => {
    const none = { ...ads, cpa: { now: 60000, after: null }, verdict: { now: "lo" as const, after: null }, verdict_text: { now: "lỗ", after: null }, profit_after_ads: { now: -900000, after: null }, roas_shopee: { now: 6, after: null }, incremental: { share: null, orders_all: null, orders_extra: null } };
    render(<OptionCard result={result({ kind: "ads_roas_target", estimable: false, ads: none })} />);
    expect(screen.getByTestId("oc-ads-cpa")).toHaveTextContent("60.000đ → —");
    expect(screen.getByTestId("oc-ads-verdict")).toHaveTextContent("lỗ → —");
    expect(screen.getByTestId("oc-ads-profit")).toHaveTextContent("−900.000đ → —");
  });

  it("other kinds carry no Ads block", () => {
    render(<OptionCard result={result()} />);
    expect(screen.queryByTestId("oc-ads")).toBeNull();
  });
});

describe("UI grill G4 · G5 · G8 on the option card", () => {
  it("names ΔGMV / chi phí from the server, never 'ROI'", () => {
    render(<OptionCard result={result({ roi: { value: 3.2, text: "3,2", metric_id: "card_return", label: "ΔGMV / chi phí" } })} />);
    expect(screen.getByText("ΔGMV / chi phí")).toBeInTheDocument();
    expect(screen.queryByText("ROI")).toBeNull();
  });

  it("a — carries the reason as its hover; the code is not shown", () => {
    render(<OptionCard result={result({ estimable: false, reason_code: "no_history", reason_text: "Sản phẩm chưa có đơn trong 30 ngày" })} />);
    const dash = within(screen.getByTestId("oc-fc-profit")).getByText("—");
    expect(dash).toHaveAttribute("title", "Sản phẩm chưa có đơn trong 30 ngày");
    expect(document.body.textContent).not.toContain("no_history");
  });

  it("a flash sale shows the money given to buyers under Chi phí", () => {
    const r = result();
    render(<OptionCard result={{ ...r, cost: { ...r.cost, discount_given: { amount: 120000, text: "Tiền giảm cho khách ~120.000 đ" } } }} />);
    expect(screen.getByTestId("oc-discount-given")).toHaveTextContent("Tiền giảm cho khách ~120.000 đ");
  });
});

describe("L1 / A9 · margin split on the option card", () => {
  const split = (over: Record<string, unknown> = {}) => ({
    with: { margin_pct: 12.34, gmv: 400000, orders: 4 },
    without: { margin_pct: 21, gmv: 600000, orders: 6 },
    unknown: null,
    ...over,
  });

  it("shows both margins next to Biên đóng góp, vi-VN decimals, no unknown share when zero", () => {
    render(<OptionCard marginSplit={split()} result={result()} />);
    expect(screen.getByTestId("oc-margin-split")).toHaveTextContent("Có giảm giá 12,3 % · Không giảm giá 21,0 %");
    expect(screen.getByTestId("oc-margin-split").textContent).not.toMatch(/Chưa rõ/);
  });

  it("a side with no purchases is a dash; unknown is only a count when non-zero", () => {
    render(<OptionCard marginSplit={split({ without: null, unknown: { orders: 3, gmv: 50000 } })} result={result()} />);
    expect(screen.getByTestId("oc-margin-split")).toHaveTextContent("Có giảm giá 12,3 % · Không giảm giá — · Chưa rõ: 3 đơn");
  });

  it("no split, no line", () => {
    render(<OptionCard result={result()} />);
    expect(screen.queryByTestId("oc-margin-split")).toBeNull();
  });
});
