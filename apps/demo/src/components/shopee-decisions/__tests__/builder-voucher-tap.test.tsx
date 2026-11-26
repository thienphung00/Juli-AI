import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ForecastBlock } from "../../../lib/shopee-decisions/forecast-display";
import type { OptionResult } from "../../../lib/shopee-decisions/option-result";
import { ResultCard } from "../builder-p92/results";

const col = { views: 1000, ctr: 5, ctor: 10, orders: 5, aov: 100_000, gmv: 500_000, profit: 100_000, by_source: {} };
type Offer = NonNullable<OptionResult["cost"]["offers"]>[number];

const result = (over: Partial<OptionResult> = {}, offers?: readonly Offer[]): OptionResult => ({
  kind: "min_spend_voucher",
  label: "Voucher",
  days: 30,
  horizon: "first_30_days",
  drivers: ["aov"],
  estimable: true,
  basis: "measured",
  basis_weak: false,
  delta: { profit: { value: 10_000, pct: 1, low: 5_000, high: 15_000 }, gmv: { value: 50_000, pct: 2 }, orders: { value: 0, pct: 0, note: null } },
  build_up: [],
  drivers_pct: [],
  cost: { total: 60_000, break_even_orders: null, break_even_aov: null, text: "", ...(offers ? { offers } : {}) },
  after: { days: 30, label: "30 ngày đầu", gmv_before: 500_000, gmv_after: 550_000, profit_before: 100_000, profit_after: 110_000 },
  per_30d: { profit: 10_000, gmv: 50_000, orders: 0 },
  detail: { before: col, low: col, likely: col, high: col },
  notes: [],
  ...over,
});

const m = (hien_tai: number | null, du_kien: number | null) => ({ hien_tai, du_kien, delta: null, delta_pct: null });
const forecast: ForecastBlock = {
  days: 30,
  metrics: { profit: m(100_000, 110_000), gmv: m(500_000, 550_000), orders: m(5, 6), aov: m(100_000, 91_667) },
};
const offer = (over: Partial<Offer> = {}): Offer => ({ label: "Giảm 5.000đ", expected_uses: 12, per_use: 5_000, total: 60_000, ...over });

const open = () => fireEvent.click(screen.getByRole("button", { name: /số liệu/i }));

describe("voucher tap-for-numbers panel", () => {
  it("N1: closed by default, a button with aria-expanded toggles it", () => {
    render(<ResultCard forecast={forecast} name="V" result={result({}, [offer()])} />);
    const btn = screen.getByRole("button", { name: /số liệu/i });
    expect(btn).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("p3-numbers")).toBeNull();
    fireEvent.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("p3-numbers")).toBeInTheDocument();
    fireEvent.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("p3-numbers")).toBeNull();
  });

  it("N2: lists each offer's uses, per use and total, and hiện tại → dự kiến for the four metrics", () => {
    render(<ResultCard forecast={forecast} name="V" result={result({}, [offer(), offer({ label: "Giảm 10%", expected_uses: 3, per_use: 8_000, total: 24_000 })])} />);
    open();
    const p = screen.getByTestId("p3-numbers");
    const o0 = within(p).getByTestId("p3-offer-0");
    expect(o0).toHaveTextContent("Giảm 5.000đ");
    expect(o0).toHaveTextContent("12");
    expect(o0).toHaveTextContent("5.000");
    expect(o0).toHaveTextContent("60.000");
    expect(within(p).getByTestId("p3-offer-1")).toHaveTextContent("24.000");
    expect(within(p).getByTestId("p3-num-profit")).toHaveTextContent("Lợi nhuận đóng góp");
    expect(within(p).getByTestId("p3-num-profit")).toHaveTextContent("100.000");
    expect(within(p).getByTestId("p3-num-profit")).toHaveTextContent("110.000");
    expect(within(p).getByTestId("p3-num-gmv")).toHaveTextContent("550.000");
    expect(within(p).getByTestId("p3-num-orders")).toHaveTextContent("5 đơn → 6 đơn");
    expect(within(p).getByTestId("p3-num-aov")).toHaveTextContent("91.667");
  });

  it("N2: a missing number reads — never 0; no offers shows — for the cost line", () => {
    const f: ForecastBlock = { metrics: { profit: m(null, null), gmv: m(500_000, null), orders: m(5, 6) } };
    render(<ResultCard forecast={f} name="V" result={result()} />);
    open();
    const p = screen.getByTestId("p3-numbers");
    expect(within(p).getByTestId("p3-offers-none")).toHaveTextContent("—");
    expect(within(p).getByTestId("p3-num-profit")).toHaveTextContent("— → —");
    expect(within(p).getByTestId("p3-num-gmv")).toHaveTextContent("500.000 đ → —");
    expect(within(p).getByTestId("p3-num-aov")).toHaveTextContent("— → —");
    expect(p.textContent).not.toMatch(/(^|[^\d.,])0\s?(đ|đơn)/);
  });

  it("N2: an empty offers list also shows — for the cost line", () => {
    render(<ResultCard forecast={forecast} name="V" result={result({}, [])} />);
    open();
    expect(screen.getByTestId("p3-offers-none")).toHaveTextContent("—");
  });

  it("N2: a missing figure inside an offer shows —", () => {
    render(<ResultCard forecast={forecast} name="V" result={result({}, [offer({ per_use: null as unknown as number })])} />);
    open();
    const t = screen.getByTestId("p3-offer-0").textContent ?? "";
    expect(t).toContain("—");
    expect(t).toContain("60.000");
  });

  it("N3: payload numbers render as given even when uses × per use differs from total", () => {
    render(<ResultCard forecast={forecast} name="V" result={result({}, [offer({ expected_uses: 7, per_use: 3_333, total: 23_000 })])} />);
    open();
    const t = screen.getByTestId("p3-offer-0").textContent ?? "";
    expect(t).toContain("7");
    expect(t).toContain("3.333");
    expect(t).toContain("23.000");
    expect(t).not.toContain("23.331");
  });

  it("N4: no method, range or explanation words", () => {
    render(<ResultCard forecast={forecast} name="V" result={result({}, [offer({ max_discount: { cap: 20_000, binding_orders: 2, qualifying_orders: 9 } })])} />);
    open();
    const t = (screen.getByTestId("p3-numbers").textContent ?? "").toLowerCase();
    for (const w of ["ước tính", "dự đoán theo", "phương pháp", "prior", "sàn", "cơ sở", "khoảng", "%", "vì ", "do "]) expect(t).not.toContain(w);
    expect(t).not.toMatch(/\bp10\b|\bp90\b/);
  });

  it("N5: other kinds render no button", () => {
    render(<ResultCard forecast={forecast} name="V" result={result({ kind: "combo" }, [offer()])} />);
    expect(screen.queryByRole("button", { name: /số liệu/i })).toBeNull();
    expect(screen.getByTestId("p3-forecast")).toBeInTheDocument();
  });

  it("shows the voucher's own offer (wire label \"voucher\") as Voucher, and the button controls its own panel", () => {
    render(
      <>
        <ResultCard forecast={forecast} name="V1" result={result({}, [offer({ label: "voucher" })])} />
        <ResultCard forecast={forecast} name="V2" result={result({}, [offer({ label: "voucher" })])} />
      </>,
    );
    const [b1, b2] = screen.getAllByRole("button", { name: /số liệu/i });
    expect(b1.getAttribute("aria-controls")).not.toBe(b2.getAttribute("aria-controls"));
    fireEvent.click(b1);
    const panel = screen.getByTestId("p3-numbers");
    expect(panel.id).toBe(b1.getAttribute("aria-controls"));
    expect(within(panel).getByTestId("p3-offer-0")).toHaveTextContent(/^Voucher/);
    expect(within(panel).queryByText("voucher")).toBeNull();
  });
});
