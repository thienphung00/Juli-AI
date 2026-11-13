import { configure, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { P_GLOVE, P_ZIP, fakeBuilder, pickerProducts } from "../../../lib/shopee-decisions/__tests__/builder-fixtures";
import type { AdsRequest, AdsResponse, BuilderP98Api, ComboRequest, ComboResponse, ComboRow, KolRequest, KolResponse } from "../../../lib/shopee-decisions/builder-p98-api";
import type { OptionResult } from "../../../lib/shopee-decisions/option-result";
import { AdsBuilder } from "../ads-builder";
import { ComboBuilder, comboTable } from "../combo-builder";
import { KolBuilder } from "../kol-builder";

configure({ asyncUtilTimeout: 4000 });

const products = pickerProducts().products;

const col = { views: 1000, ctr: 5, ctor: 10, orders: 5, aov: 100_000, gmv: 500_000, profit: 100_000, by_source: {} };
// a complete wire result (option-result.ts), as the real OptionCard / CompareTable read it
const result = (label: string): OptionResult => ({
  kind: "listing_combo",
  label,
  days: 30,
  horizon: "first_30_days",
  drivers: ["aov"],
  estimable: true,
  basis: "measured",
  basis_weak: false,
  delta: { profit: { value: 10_000, pct: 1, low: 5_000, high: 15_000 }, gmv: { value: 50_000, pct: 2 }, orders: { value: 0, pct: 0, note: null } },
  build_up: [],
  drivers_pct: [{ metric: "aov", label: "AOV", pct: 2 }],
  cost: { total: 0, break_even_orders: null, break_even_aov: null, text: "" },
  after: { days: 30, label: "30 ngày đầu", gmv_before: 500_000, gmv_after: 550_000, profit_before: 100_000, profit_after: 110_000 },
  per_30d: { profit: 10_000, gmv: 50_000, orders: 0 },
  detail: { before: col, low: col, likely: col, high: col },
  notes: [],
});

const row = (key: string, over: Partial<ComboRow> = {}): ComboRow => ({
  key,
  form: "multipack",
  name: "Túi zip",
  option_name: `Combo ${key}`,
  sku: `SKU-${key}`,
  units: 3,
  members: [],
  suggested_stock: 40,
  stock_note: null,
  price: 87_000,
  price_per_box: 29_000,
  separate_total: 99_000,
  saving: 12_000,
  saving_pct: 12.1,
  margin_pct: 16.5,
  final_margin_pct: 9.5,
  profit_per_order: 13_900,
  margin_label: null,
  below_floor: false,
  overridden: false,
  notes: [],
  ...over,
});

function comboApi(rows: ComboRow[] = [row("a"), row("b")], over: Partial<ComboResponse> = {}) {
  const calls: ComboRequest[] = [];
  const api: BuilderP98Api = {
    combo: (req) => {
      calls.push(req);
      return Promise.resolve({ as_of: "2026-11-09", count: { total: 12, kept: rows.length, over_cap: 10, by_form: {} }, warnings: ["Vượt giới hạn: chỉ giữ 2 phương án"], floor_pct: null, rows, ...over });
    },
    kol: () => Promise.reject(new Error("no")),
    ads: () => Promise.reject(new Error("no")),
  };
  return { api, calls };
}

async function openCombo(api: BuilderP98Api) {
  render(<ComboBuilder api={api} products={products} variationsApi={fakeBuilder()} />);
  fireEvent.click(screen.getByRole("button", { name: "Túi zip thực phẩm D" }));
  await screen.findByTestId(`combo-vars-${P_ZIP}`);
  await screen.findByLabelText("Combo 3 hộp");
}

describe("P98 combo builder", () => {
  it("shows the count and warnings before the table is built", async () => {
    const { api } = comboApi();
    await openCombo(api);
    expect(await screen.findByTestId("combo-count-total")).toHaveTextContent("12 phương án");
    expect(screen.getByRole("status")).toHaveTextContent("Vượt giới hạn");
    expect(screen.queryByTestId("combo-table")).toBeNull();
    fireEvent.click(screen.getByTestId("combo-build"));
    expect(await screen.findByTestId("combo-table")).toBeInTheDocument();
  });

  it("rules toggles and pack sizes change the request", async () => {
    const { api, calls } = comboApi();
    await openCombo(api);
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    expect(calls.at(-1)!.rules).toMatchObject({ same_variation: true, sold_only: true });
    fireEvent.click(screen.getByLabelText("Cùng phân loại trong một gói"));
    fireEvent.click(screen.getByLabelText("Chỉ phân loại có bán 30 ngày"));
    fireEvent.change(screen.getByLabelText("Tối đa số phương án"), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "5 hộp" }));
    fireEvent.change(screen.getByLabelText("Cỡ khác (hộp)"), { target: { value: "7" } });
    await waitFor(() => expect(calls.at(-1)!.rules).toMatchObject({ same_variation: false, sold_only: false, max_options: 20 }));
    await waitFor(() => expect(calls.at(-1)!.pack_sizes).toEqual([3, 10, 7]));
    expect(calls.at(-1)!.products[0]!.variation_ids).toEqual(["v3", "v5", "v10"]);
  });

  it("re-requests with the price override of a row and renders both margins", async () => {
    const { api, calls } = comboApi([row("a", { below_floor: true })]);
    await openCombo(api);
    fireEvent.click(await screen.findByTestId("combo-build"));
    const table = await screen.findByTestId("combo-table");
    expect(table).toHaveTextContent("Biên ở giá bán (chắc chắn)");
    expect(table).toHaveTextContent("Biên cuối");
    expect(table).toHaveTextContent("16,5%");
    expect(table).toHaveTextContent("9,5%");
    expect(table).toHaveTextContent("không tự đồng bộ");
    expect(table).toHaveTextContent("Dưới ngưỡng biên tối thiểu");
    const input = screen.getByLabelText("Giá Combo a");
    fireEvent.change(input, { target: { value: "90000" } });
    fireEvent.blur(input);
    await waitFor(() => expect(calls.at(-1)!.overrides).toEqual({ a: 90_000 }));
  });

  it("copies the table as tab separated text", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const rows = [row("a")];
    const { api } = comboApi(rows);
    await openCombo(api);
    fireEvent.click(await screen.findByTestId("combo-build"));
    fireEvent.click(await screen.findByRole("button", { name: "Sao chép bảng" }));
    expect(writeText).toHaveBeenCalledWith(comboTable(rows));
    const text = comboTable(rows);
    expect(text.split("\n")[1]).toBe(["Combo a", "SKU-a", 87000, 29000, 12000, 16.5, 9.5, 13900, 40].join("\t"));
    expect(text.split("\n")[0]).toContain("\t");
  });

  it("renders result cards and a compare table when rows carry a result", async () => {
    const { api } = comboApi([row("a", { result: result("Phương án A") }), row("b", { result: result("Phương án B") })]);
    await openCombo(api);
    fireEvent.click(await screen.findByTestId("combo-build"));
    expect(await screen.findAllByTestId("option-card")).toHaveLength(2);
    const cmp = screen.getByTestId("oc-compare");
    expect(cmp).toHaveTextContent("Phương án A");
    expect(cmp).toHaveTextContent("Phương án B");
  });
});

describe("P98 KOL builder", () => {
  const kolResp = (withResult: boolean): KolResponse => ({
    as_of: "2026-11-09",
    labels: {},
    setups: [
      {
        kol: { kol_key: "k1", handle: "@mai", channel: "tiktok" },
        commission_pct: 10,
        products: [],
        sample: { item_id: P_GLOVE, qty: 2, ship_fee: 30_000, unit_cost: 20_000, unit_cost_basis: null, cost: 70_000, cost_note: null },
        ...(withResult ? { result: result("KOL Mai") } : {}),
      },
    ],
  });

  it("labels cashback affiliates and offers no sample for them", () => {
    const api = { kol: vi.fn() } as unknown as BuilderP98Api;
    render(<KolBuilder api={api} kols={[{ kol_key: "k1", handle: "@mai", kind: "kol" }, { kol_key: "c1", handle: "Shopback", kind: "cashback" }]} products={products} />);
    expect(screen.getByRole("button", { name: /Shopback.*trang hoàn tiền \/ mã giảm giá/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Shopback/ }));
    expect(screen.queryByLabelText("Gửi hàng mẫu")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /@mai/ }));
    expect(screen.getByLabelText("Gửi hàng mẫu")).toBeInTheDocument();
  });

  it("sends commission and sample, shows the sample cost and the result card", async () => {
    const calls: KolRequest[] = [];
    const api = { kol: (r: KolRequest) => (calls.push(r), Promise.resolve(kolResp(true))) } as unknown as BuilderP98Api;
    render(<KolBuilder api={api} kols={[{ kol_key: "k1", handle: "@mai" }]} products={products} />);
    fireEvent.click(screen.getByRole("button", { name: "@mai" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Găng tay cao su A" })[0]!);
    fireEvent.change(screen.getByLabelText("Hoa hồng k1 (%)"), { target: { value: "12" } });
    fireEvent.click(screen.getByLabelText("Gửi hàng mẫu"));
    fireEvent.change(screen.getByLabelText("Số lượng mẫu"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Phí ship (đ)"), { target: { value: "30000" } });
    fireEvent.click(screen.getByTestId("kol-calc"));
    expect(await screen.findByTestId("kol-out")).toHaveTextContent("70.000");
    expect(calls[0]!.kols[0]).toMatchObject({ kol_key: "k1", item_ids: [P_GLOVE], commission_pct: 12, sample: { item_id: P_GLOVE, qty: 2, ship_fee: 30_000 } });
    expect(screen.getByTestId("option-card")).toHaveTextContent("KOL Mai");
  });
});

describe("P98 ads builder", () => {
  it("refuses a budget under the minimum and sends a valid setup", async () => {
    const calls: AdsRequest[] = [];
    const out: AdsResponse = { as_of: "2026-11-09", budget_minimum: 100_000, setups: [{ campaign: "group", campaign_label: "Chiến dịch nhóm", name: null, daily_budget: 150_000, days: 7, total_budget: 1_050_000, products: [], result: result("Ads 1") }] };
    const api = { ads: (r: AdsRequest) => (calls.push(r), Promise.resolve(out)) } as unknown as BuilderP98Api;
    render(<AdsBuilder api={api} products={products} />);
    expect(screen.getByText(/nhập thiết lập bằng tay/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Găng tay cao su A" }));
    fireEvent.change(screen.getByLabelText("Ngân sách mỗi ngày 1 (đ)"), { target: { value: "50000" } });
    fireEvent.change(screen.getByLabelText("Ngày bắt đầu 1"), { target: { value: "2026-11-10" } });
    fireEvent.click(screen.getByTestId("ads-calc"));
    expect(screen.getByRole("alert")).toHaveTextContent("Ngân sách mỗi ngày tối thiểu 100.000");
    expect(calls).toHaveLength(0);
    fireEvent.change(screen.getByLabelText("Ngân sách mỗi ngày 1 (đ)"), { target: { value: "150000" } });
    fireEvent.change(screen.getByLabelText("Ngày kết thúc 1 (không bắt buộc)"), { target: { value: "2026-11-16" } });
    fireEvent.click(screen.getByTestId("ads-calc"));
    expect(await screen.findByTestId("ads-out")).toHaveTextContent("7 ngày");
    expect(calls[0]!.setups[0]).toMatchObject({ campaign: "group", item_ids: [P_GLOVE], daily_budget: 150_000, roas: { mode: "system" }, start_date: "2026-11-10", end_date: "2026-11-16" });
    expect(screen.getByTestId("option-card")).toHaveTextContent("Ads 1");
  });

  it("adds a second setup side by side and compares the results", async () => {
    const mk = (n: string) => ({ campaign: "group" as const, campaign_label: "Chiến dịch nhóm", name: null, daily_budget: 100_000, days: null, total_budget: null, products: [], result: result(n) });
    const api = { ads: () => Promise.resolve({ as_of: "x", budget_minimum: 100_000, setups: [mk("S1"), mk("S2")] }) } as unknown as BuilderP98Api;
    render(<AdsBuilder api={api} products={products} />);
    fireEvent.click(screen.getByRole("button", { name: "+ Thêm thiết lập" }));
    for (const i of [0, 1]) {
      fireEvent.click(screen.getAllByRole("button", { name: "Găng tay cao su A" })[i]!);
      fireEvent.change(screen.getByLabelText(`Ngày bắt đầu ${i + 1}`), { target: { value: "2026-11-10" } });
    }
    fireEvent.click(screen.getByTestId("ads-calc"));
    const cmp = await screen.findByTestId("oc-compare");
    expect(cmp).toHaveTextContent("S1");
    expect(cmp).toHaveTextContent("S2");
  });
});
