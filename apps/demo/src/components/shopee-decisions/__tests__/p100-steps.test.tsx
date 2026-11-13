import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BuilderApi, BuilderOutcome, PickerProduct } from "../../../lib/shopee-decisions/builder-api";
import { initialForms } from "../../../lib/shopee-decisions/builder-p92";
import type { FunnelColumn, OptionResult } from "../../../lib/shopee-decisions/option-result";
import type { Entry } from "../builder-p92/compare";
import { StepPhuongAn } from "../builder-p92/step-phuong-an";
import { StepSoSanh } from "../builder-p92/step-so-sanh";

const col: FunnelColumn = { views: 1000, ctr: 3, ctor: 4, orders: 90, aov: 200000, gmv: 18000000, profit: 3000000, by_source: {} };

function ads(over: Partial<NonNullable<OptionResult["ads"]>> = {}): NonNullable<OptionResult["ads"]> {
  return {
    lever: "budget",
    campaign: "Chiến dịch A",
    days: 30,
    spend_basis: "history",
    spend_text: "x",
    spend: { now: 3000000, after: 2400000 },
    orders: { now: 90, after: 72 },
    cpa: { now: 33333, after: 33333 },
    break_even_cpa: 50000,
    verdict: { now: "co_lai", after: "co_lai" },
    verdict_text: { now: "có lãi", after: "có lãi" },
    profit_after_ads: { now: 1500000, after: 1200000 },
    roas_shopee: { now: 5, after: 5 },
    incremental: { share: 50, orders_all: -18, orders_extra: -9 },
    cancel_rate_pct: 10,
    ...over,
  };
}

function res(profit: number, gmv: number, over: Partial<OptionResult> = {}): OptionResult {
  return {
    kind: "ads_budget",
    label: "Ngân sách 80.000đ/ngày",
    days: 30,
    horizon: "duration",
    drivers: ["views"],
    estimable: true,
    basis: "product_history",
    basis_weak: false,
    delta: { profit: { value: profit, pct: null, low: null, high: null }, gmv: { value: gmv, pct: null }, orders: { value: -18, pct: null, note: null } },
    build_up: [],
    drivers_pct: [],
    cost: { total: -600000, break_even_orders: null, break_even_aov: null, text: "" },
    after: { days: 30, label: "30 ngày", gmv_before: 1, gmv_after: 1, profit_before: 1, profit_after: 1 },
    per_30d: { profit: profit, gmv: gmv, orders: -18 },
    roi: { value: 1.95, text: null },
    detail: { before: col, low: null, likely: col, high: null },
    notes: [],
    ads: ads(),
    ...over,
  };
}

const outcome = (index: number, r: OptionResult, label = r.label): BuilderOutcome => ({ index, kind: "ads", label, ok: true, result: r });

const product = { item_id: "P1", name: "Găng tay" } as unknown as PickerProduct;

function stepApi(): BuilderApi {
  return { adsCampaigns: vi.fn().mockResolvedValue({ daily_cap: null, campaigns: [{ campaign_key: "c1", name: "GMV tối đa", daily_budget: 100000, roas_target: 4, spend_per_day: 100000, roas_direct: 5, break_even_roas: 3, products: [] }] }) } as unknown as BuilderApi;
}

function renderStep3(r: OptionResult, extra: Record<string, unknown> = {}) {
  const forms = initialForms();
  const props = {
    kind: "ads" as const,
    kindLabel: "Dịch vụ hiển thị",
    productName: "Găng tay",
    forms,
    setForm: vi.fn(),
    ctx: { api: stepApi(), product, variations: [], products: [product], aov: null, outcome: outcome(0, r), narrow: false, costLink: "/c", market: null },
    state: { status: "ready" as const, outcome: outcome(0, r) },
    costLink: "/c",
    index: 0,
    editing: null,
    entries: [] as Entry[],
    canAdd: true,
    onUntick: vi.fn(),
    onAdd: vi.fn(),
    onReset: vi.fn(),
    onBack: vi.fn(),
    ...extra,
  };
  render(<StepPhuongAn {...props} />);
  return props;
}

describe("P100 step ③ Phương án", () => {
  it("a profitable ads edit: finding title, verdict, period totals with ≈ per day, CPA bar and the ads rows", async () => {
    renderStep3(res(150000, -1170000));
    expect(screen.getByTestId("p3-title")).toHaveTextContent("Chiến dịch đang có lãi: CPA 33.333đ, hoà vốn 50.000đ");
    expect(screen.getByTestId("p3-verdict")).toHaveTextContent("Có lãi");
    expect(screen.getByTestId("p3-dprofit")).toHaveTextContent("Δ lợi nhuận cả 30 ngày");
    expect(screen.getByTestId("p3-dprofit")).toHaveTextContent("+150.000đ");
    expect(screen.getByTestId("p3-dprofit-perday")).toHaveTextContent("≈ +5.000đ/ngày");
    expect(screen.getByTestId("p3-dgmv")).toHaveTextContent("−1.170.000đ");
    expect(screen.getByTestId("p3-dgmv-perday")).toHaveTextContent("≈ −39.000đ/ngày");
    expect(screen.getByTestId("p3-cpa")).toHaveTextContent("Hoà vốn 50.000đ");
    expect(screen.getByTestId("p3-cpa-mark")).toBeInTheDocument();
    expect(screen.getByTestId("p3-row-spend")).toHaveTextContent("Chi phí cả kỳ3.000.000đ → 2.400.000đ");
    expect(screen.getByTestId("p3-row-orders")).toHaveTextContent("90 → 72 (−18)");
    expect(screen.getByTestId("p3-row-lost")).toHaveTextContent("−9");
    expect(screen.getByTestId("p3-row-profit")).toHaveTextContent("1.500.000đ → 1.200.000đ");
    expect(screen.getByTestId("p3-row-roas")).toHaveTextContent("ROAS Shopee5,0");
    // the ads panel: campaign select, four lever tabs, today's values
    expect(await screen.findByRole("option", { name: "GMV tối đa" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Ngân sách", "ROAS mục tiêu", "Thêm sản phẩm", "Bớt sản phẩm"]);
    expect(screen.getByTestId("p3-ads-today")).toHaveTextContent("Hiện tại:");
  });

  it("a losing edit reads Lỗ phần thêm with the amount", () => {
    renderStep3(res(-150000, 1170000));
    expect(screen.getByTestId("p3-verdict")).toHaveTextContent("Lỗ phần thêm 150.000đ");
    expect(screen.getByTestId("p3-dprofit-perday")).toHaveTextContent("≈ −5.000đ/ngày");
  });

  it("another kind keeps only its own rows (no CPA bar)", () => {
    renderStep3(res(90000, 500000, { kind: "voucher", ads: null, cost: { total: 90000, break_even_orders: null, break_even_aov: null, text: "" } }), { kind: "voucher", kindLabel: "Voucher" });
    expect(screen.queryByTestId("p3-cpa")).toBeNull();
    expect(screen.getByTestId("p3-dprofit-perday")).toHaveTextContent("≈ +3.000đ/ngày");
    expect(screen.getByTestId("p3-row-cost")).toHaveTextContent("90.000đ");
    expect(screen.queryByTestId("p3-row-spend")).toBeNull();
  });

  it("version rows: P1 saved, the live row is P2; add and compare buttons", () => {
    const e: Entry = { id: 1, kind: "ads", forms: initialForms(), version: { kind: "ads", label: "Ngân sách 80.000" } };
    const onSelect = vi.fn();
    const p = renderStep3(res(150000, 0), { entries: [e], index: 1, onSelect, onNext: vi.fn() });
    expect(screen.getByTestId("p3-version-1")).toHaveTextContent("P1");
    expect(screen.getByTestId("p3-version-2")).toHaveTextContent("P2");
    fireEvent.click(screen.getByTestId("p3-version-1"));
    expect(onSelect).toHaveBeenCalledWith(0);
    fireEvent.click(screen.getByRole("button", { name: "+ Thêm phương án" }));
    expect(p.onAdd).toHaveBeenCalled();
    expect(screen.getByTestId("p3-next")).toHaveTextContent("So sánh 1 phương án");
  });
});

function entry(id: number, label: string): Entry {
  return { id, kind: "ads", forms: initialForms(), version: { kind: "ads", label } };
}

function compareApi(outcomes: BuilderOutcome[]) {
  const evaluation = { versions: outcomes, today: {} };
  return {
    compare: vi.fn().mockResolvedValue(evaluation),
    evaluate: vi.fn().mockResolvedValue(evaluation),
    choose: vi.fn().mockResolvedValue({ id: "c1", code: "JC-1", status: "proposed" }),
  };
}

function renderStep4(api: ReturnType<typeof compareApi>) {
  const entries = [entry(1, "80.000 đ/ngày"), entry(2, "120.000 đ/ngày"), entry(3, "ROAS 6")];
  const onBack = vi.fn();
  render(<StepSoSanh api={api as unknown as BuilderApi} costLink="/c" entries={entries} narrow={false} onAdd={vi.fn()} onBack={onBack} onEdit={vi.fn()} onRemove={vi.fn()} planHref={null} productName="Găng tay" readOnly={false} staffDraft={false} />);
  return { onBack };
}

const three = (): BuilderOutcome[] => [outcome(0, res(150000, -1170000)), outcome(1, res(-150000, 1170000, { ads: ads({ cpa: { now: 33333, after: 60000 }, verdict: { now: "co_lai", after: "lo" } }) })), outcome(2, res(200000, -260000))];

describe("P100 step ④ So sánh & lưu", () => {
  it("names the best version in the title with the period total; bars: gain grey on the right, loss red on the left; per-day lines", async () => {
    renderStep4(compareApi(three()));
    expect(await screen.findByTestId("p4-title")).toHaveTextContent("P3 lãi thêm nhiều nhất: +200.000đ trong 30 ngày");
    expect(screen.getByTestId("p4-bar-fill-1")).toHaveAttribute("data-sign", "gain");
    expect(screen.getByTestId("p4-bar-fill-2")).toHaveAttribute("data-sign", "loss");
    expect(screen.getByTestId("p4-bar-fill-3").style.width).toBe("50%");
    expect(screen.getByTestId("p4-bar-fill-2").style.right).toBe("50%");
    expect(screen.getByTestId("p4-bar-fill-1").style.left).toBe("50%");
    expect(screen.getByTestId("p4-profit-1")).toHaveTextContent("+150.000đ");
    expect(screen.getByTestId("p4-profit-perday-3")).toHaveTextContent("≈ +6.667đ/ngày");
    expect(screen.getByTestId("p4-profit-2")).toHaveTextContent("−150.000đ");
  });

  it("the table has Δ GMV (total + per day), Chi phí, Đơn QC, CPA / hoà vốn, ROI and the verdict", async () => {
    renderStep4(compareApi(three()));
    await screen.findByTestId("p4-table");
    const heads = within(screen.getByTestId("p4-table")).getAllByRole("columnheader").map((h) => h.textContent);
    expect(heads).toEqual(["cả 30 ngày", "Δ GMV", "Chi phí", "Đơn QC", "CPA / hoà vốn", "ROI", "Kết luận"]);
    const row = screen.getByTestId("p4-row-1");
    expect(row).toHaveTextContent("−1.170.000đ");
    expect(row).toHaveTextContent("≈ −39.000đ/ngày");
    expect(row).toHaveTextContent("2.400.000đ (−600.000đ)");
    expect(row).toHaveTextContent("72 (−18)");
    expect(row).toHaveTextContent("33.333 / 50.000");
    expect(row).toHaveTextContent("1,95");
    expect(screen.getByTestId("p4-verdict-1")).toHaveTextContent("Có lãi");
    expect(screen.getByTestId("p4-verdict-2")).toHaveTextContent("Lỗ phần thêm 150.000đ");
  });

  it("saves the picked main version with the Quyết định checkbox as `primary`; the others stay versions", async () => {
    const api = compareApi(three());
    const { onBack } = renderStep4(api);
    await screen.findByTestId("p4-table");
    // best (P3) is the default main version
    expect(screen.getByRole("radio", { name: "P3 là phương án chính" })).toBeChecked();
    expect(screen.getByTestId("p4-others")).toHaveTextContent("P1 · P2 lưu làm phiên bản");
    fireEvent.click(screen.getByRole("radio", { name: "P1 là phương án chính" }));
    expect(screen.getByTestId("p4-others")).toHaveTextContent("P2 · P3 lưu làm phiên bản");
    fireEvent.click(screen.getByRole("checkbox", { name: "Đưa lên Quyết định ngay" }));
    fireEvent.click(screen.getByTestId("p4-save"));
    await waitFor(() => expect(api.choose).toHaveBeenCalledTimes(1));
    expect(api.choose.mock.calls[0]![0]).toMatchObject({ chosen: 0, primary: true, acknowledgeBreaches: false });
    expect(api.choose.mock.calls[0]![0].versions).toHaveLength(3);
    expect(await screen.findByTestId("p4-saved")).toHaveTextContent("Đã lưu · JC-1");
    fireEvent.click(screen.getByTestId("p4-edit"));
    expect(onBack).toHaveBeenCalled();
  });

  it("Chạy cùng nhau sits under the table, before the main-version row, and sends one group call", async () => {
    const api = { ...compareApi(three()), group: vi.fn().mockResolvedValue({ saved: [{ id: "c1", code: "JC-9", indexes: [0, 1] }], groups: [], placed: [] }) };
    renderStep4(api);
    await screen.findByTestId("p4-table");
    const together = screen.getByTestId("p2-together");
    expect(screen.getByTestId("p4-table").compareDocumentPosition(together) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(together.compareDocumentPosition(screen.getByTestId("p4-save")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByTestId("p2-together-go")).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Chạy cùng nhau P1" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Chạy cùng nhau P2" }));
    fireEvent.change(screen.getByLabelText("Số ngày của nhóm"), { target: { value: "2" } });
    expect(screen.getByText("Nhóm chạy ít nhất 3 ngày.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Số ngày của nhóm"), { target: { value: "5" } });
    expect(screen.getByTestId("p2-together-go")).toHaveTextContent("(2 phương án)");
    fireEvent.click(screen.getByTestId("p2-together-go"));
    await waitFor(() => expect(api.group).toHaveBeenCalledTimes(1));
    expect(api.group.mock.calls[0]![0]).toMatchObject({ members: [0, 1], days: 5, acknowledgeBreaches: false });
    expect(await screen.findByTestId("p2-together-result")).toHaveTextContent("JC-9");
  });

  it("without the checkbox primary is false", async () => {
    const api = compareApi(three());
    renderStep4(api);
    await screen.findByTestId("p4-table");
    fireEvent.click(screen.getByTestId("p4-save"));
    await waitFor(() => expect(api.choose).toHaveBeenCalled());
    expect(api.choose.mock.calls[0]![0]).toMatchObject({ chosen: 2, primary: false });
  });
});
