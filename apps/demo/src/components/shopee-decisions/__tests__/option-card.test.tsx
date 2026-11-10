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
    detail: { before: col(), low: col({ orders: 105 }), likely: col({ orders: 112 }), high: col({ orders: 120 }) },
    notes: ["Số liệu 28 ngày gần nhất."],
    ...over,
  };
}

describe("P98 W3-I · OptionCard", () => {
  it("shows exactly the d.5 lines, formatted vi-VN", () => {
    render(<OptionCard result={result()} />);
    expect(screen.getByTestId("oc-profit")).toHaveTextContent("+1.234.567đ · +5,5% (+500.000đ … +2.000.000đ)");
    expect(screen.getByTestId("oc-buildup")).toHaveTextContent("+300.000đ từ đơn thêm. −50.000đ giảm giá.");
    expect(screen.getByTestId("oc-gmv")).toHaveTextContent("+2.500.000đ · +12,5%");
    expect(screen.getByTestId("oc-orders")).toHaveTextContent("+12 · +12,0%");
    expect(screen.getByTestId("oc-drivers")).toHaveTextContent("AOV +1,7% · CTOR +1,8%");
    expect(screen.getByTestId("oc-cost")).toHaveTextContent("150.000đ Chi phí 150.000đ · hoà vốn khi thêm ≥ 5 đơn");
    expect(screen.getByTestId("oc-after")).toHaveTextContent("GMV 20.000.000đ → 22.500.000đ · Lợi nhuận 3.000.000đ → 4.234.567đ");
    expect(screen.getByTestId("oc-after").previousElementSibling).toHaveTextContent("Sau 7 ngày");
    expect(screen.queryByTestId("oc-weak")).toBeNull();
    expect(screen.queryByTestId("oc-detail")).toBeNull();
    expect(screen.getAllByRole("term").map((t) => t.textContent)).toEqual(["Δ Lợi nhuận", "Δ GMV", "Δ Đơn", "Tác động", "Chi phí", "Hoà vốn", "Sau 7 ngày"]);
  });

  it("null profit reads 'chưa ước tính được' with the note; costless-unknown reads 'chưa tính'", () => {
    const note = "Chưa ước tính được.";
    const r = result({ estimable: false, delta: { profit: null, gmv: { value: null, pct: null }, orders: { value: 0, pct: null, note } }, build_up: [], after: { days: 7, label: "Sau 7 ngày", gmv_before: 1, gmv_after: null, profit_before: null, profit_after: null } });
    render(<OptionCard result={r} />);
    expect(screen.getByTestId("oc-profit")).toHaveTextContent("chưa ước tính được");
    expect(screen.getByTestId("oc-note")).toHaveTextContent(note);
    expect(screen.getByTestId("oc-gmv")).toHaveTextContent("chưa ước tính được");
    expect(screen.getByTestId("oc-orders")).toHaveTextContent("chưa ước tính được");
    expect(screen.getByTestId("oc-orders")).not.toHaveTextContent("+0");
    expect(screen.queryByTestId("oc-after")).toBeNull();
  });

  it("'chưa tính' when estimable but profit unknown", () => {
    render(<OptionCard result={result({ delta: { profit: null, gmv: { value: 1000, pct: 1 }, orders: { value: 1, pct: 1, note: null } } })} />);
    expect(screen.getByTestId("oc-profit")).toHaveTextContent("chưa tính");
  });

  it("AOV-only: +0 orders and the note", () => {
    const note = "Đòn bẩy này tăng giá trị mỗi đơn, không tăng số đơn.";
    render(<OptionCard result={result({ drivers: ["aov"], delta: { profit: { value: 100000, pct: 3, low: 50000, high: 150000 }, gmv: { value: 500000, pct: 2 }, orders: { value: 0, pct: 0, note } } })} />);
    expect(screen.getByTestId("oc-orders")).toHaveTextContent("+0");
    expect(screen.getByTestId("oc-note")).toHaveTextContent(note);
  });

  it("shows the 'ước tính chung' tag only when basis_weak; uses '30 ngày đầu' for first_30_days", () => {
    const { rerender } = render(<OptionCard result={result({ basis: "prior", basis_weak: true, horizon: "first_30_days", after: { days: 30, label: "30 ngày đầu", gmv_before: 1, gmv_after: 2, profit_before: 1, profit_after: 2 } })} />);
    expect(screen.getByTestId("oc-weak")).toHaveTextContent("ước tính chung");
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
    expect(row).toHaveTextContent("+1.234.567đ · +5,5%");
    expect(row).toHaveTextContent("+2.500.000đ · +12,5%");
    expect(row).toHaveTextContent("+12 · +12,0%");
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
    expect(screen.getByTestId("oc-orders")).toHaveTextContent("chưa ước tính được");
    expect(screen.getByTestId("oc-orders")).not.toHaveTextContent("+0");
  });

  it("Δ Đơn is shown as the backend rounded it: one decimal under 10, whole from 10", () => {
    const { rerender } = render(<OptionCard result={result({ delta: { profit: null, gmv: { value: 1, pct: 1 }, orders: { value: 7.7, pct: 8, note: null } } })} />);
    expect(screen.getByTestId("oc-orders")).toHaveTextContent("+7,7 ·");
    rerender(<OptionCard result={result({ delta: { profit: null, gmv: { value: 1, pct: 1 }, orders: { value: 13, pct: 8, note: null } } })} />);
    expect(screen.getByTestId("oc-orders")).toHaveTextContent("+13 ·");
  });
});
