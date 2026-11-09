import type {
  BuilderApi,
  BuilderEvaluation,
  BuilderOutcome,
  BuilderVersion,
  ChooseResult,
  CoPurchase,
  ExclusionList,
  GroupResult,
  KeywordTable,
  PickerProduct,
  PickerResult,
  VariationList,
} from "../builder-api";

/** Synthetic P92 builder data (household-goods shop of the artboards; invented numbers, no shop data). */

export const P_ZIP = "21870465320";
export const P_GLOVE = "18453209761";
export const P_SPONGE = "19320487455";
export const P_LEMON = "22734190852";
export const P_IDLE = "23190774615";

const product = (item_id: string, name: string, over: Partial<PickerProduct> = {}): PickerProduct => ({
  item_id,
  name,
  status: "Đang hoạt động",
  orders_30d: 10,
  orders_90d: 30,
  gmv_30d: 1_000_000,
  gmv_90d: 3_000_000,
  gmv_basis: "order_lines",
  price: 90_000,
  stock: 100,
  variation_count: 3,
  has_cost: true,
  variations_with_cost: 3,
  missing_cost_chip: null,
  excluded: false,
  exclude_reason: null,
  ...over,
});

export function pickerProducts(): PickerResult {
  const products = [
    product(P_ZIP, "Túi zip thực phẩm D", { orders_30d: 210, orders_90d: 598, gmv_90d: 70_564_000, category: "Túi đựng thực phẩm", margin_pct: 14.1, in_ads: true }),
    product(P_GLOVE, "Găng tay cao su A", { orders_30d: 187, orders_90d: 521, gmv_90d: 51_058_000, category: "Găng tay", margin_pct: 31.5, ctor_down: true, has_proposal: true }),
    product(P_SPONGE, "Miếng rửa chén C", { orders_30d: 305, orders_90d: 842, gmv_90d: 30_312_000, variation_count: 0, category: "Dụng cụ rửa chén", margin_pct: 8.2, in_kol: true }),
    product(P_LEMON, "Nước rửa chén hương chanh E", { orders_30d: 71, orders_90d: 233, gmv_90d: 15_844_000, has_cost: false, missing_cost_chip: "thiếu giá vốn" }),
    product(P_IDLE, "Màng bọc thực phẩm G", { orders_30d: 0, orders_90d: 58, gmv_90d: 3_016_000, has_cost: false, missing_cost_chip: "thiếu giá vốn" }),
    ...Array.from({ length: 7 }, (_, i) => product(`9000${i}`, `Sản phẩm mẫu ${i + 1}`, { orders_30d: 5, gmv_90d: 2_000_000 - i * 1000 })),
  ];
  return {
    platform: "shopee",
    window: { from: "2026-08-10", to: "2026-11-07", days: 90 },
    sort: "gmv_90d",
    count: products.length,
    offset: 0,
    limit: 1000,
    excluded_hidden: 4,
    missing_cost_count: 2,
    products,
  };
}

export function variationList(itemId = P_ZIP): VariationList {
  return {
    item_id: itemId,
    name: "Túi zip thực phẩm D",
    excluded: false,
    exclude_reason: null,
    columns: ["list_price", "selling_price", "price_per_unit", "margin_pct"],
    margin_basis: "Biên của một đơn gồm 1 đơn vị bán của phân loại này, sau phí sàn, giá vốn, đóng gói và VAT",
    missing_cost: ["v10"],
    variations: [
      { variation_id: "v3", name: "Combo 3 hộp", sku: "TZ-D-3", list_price: 99_000, selling_price: 87_000, pack_count: 3, pack_source: "name", price_per_unit: 29_000, margin_pct: 16, profit_per_unit: 13_900, margin_label: null, margin_reason: null, has_cost: true, stock: 90 },
      { variation_id: "v5", name: "Combo 5 hộp", sku: "TZ-D-5", list_price: 159_000, selling_price: 139_000, pack_count: 5, pack_source: "name", price_per_unit: 27_800, margin_pct: 14.1, profit_per_unit: 19_600, margin_label: null, margin_reason: null, has_cost: true, stock: 50 },
      { variation_id: "v10", name: "Combo 10 hộp", sku: "TZ-D-10", list_price: 299_000, selling_price: 259_000, pack_count: 10, pack_source: "name", price_per_unit: 25_900, margin_pct: null, profit_per_unit: null, margin_label: "chưa tính", margin_reason: "Chưa có giá vốn trong Thông số shop", has_cost: false, stock: 20 },
    ],
  };
}

export function coPurchase(): CoPurchase {
  return {
    anchor: { item_id: P_ZIP, name: "Túi zip thực phẩm D" },
    orders_with_anchor: 90,
    orders_total: 210,
    suggestions: [{ item_id: P_SPONGE, name: "Miếng rửa chén C", together: 41, orders_with_partner: 60, share_of_anchor_orders: 0.45, share_of_partner_orders: 0.6 }],
  };
}

export function keywordTable(): KeywordTable {
  return {
    item_id: P_ZIP,
    title: "Túi zip thực phẩm 20 túi",
    title_chars: 25,
    max_title_chars: 100,
    sources: [
      { key: "title", label: "Tiêu đề hiện tại", present: true, count: 2, reason: null },
      { key: "ads", label: "Báo cáo từ khoá quảng cáo", present: false, count: 0, reason: "Báo cáo từ khoá quảng cáo chưa có dòng nào cho sản phẩm này." },
    ],
    keywords: [
      { keyword: "túi zip thực phẩm", sources: ["title"], volume: 12_400, difficulty: 40, in_title: true },
      { keyword: "túi zip đựng đồ ăn", sources: ["suggestion"], volume: 5_100, difficulty: 20, in_title: false },
      { keyword: "túi bảo quản tủ lạnh", sources: ["competitor"], volume: null, difficulty: null, volume_status: "chua_tra", in_title: false },
    ],
  };
}

export function outcome(index = 0, over: Partial<BuilderOutcome> = {}): BuilderOutcome {
  return {
    index,
    kind: "voucher",
    label: `V${index + 1}`,
    ok: true,
    refusal: null,
    title: "Voucher đơn tối thiểu",
    driver: {
      metrics: [
        { key: "aov", label: "AOV", unit: "vnd", before: 124_143, after_p50: 127_364 },
        { key: "ctor", label: "CTOR", unit: "pct", before: 2.5, after_p50: 2.69 },
      ],
      target_metric: "aov",
    },
    delta: {
      gmv: { low: 1_409_000, p50: 2_714_000 + index * 1000, high: 4_144_000 },
      orders: { low: 8, p50: 16, high: 25 },
      profit: { low: -157_000, p50: 54_000 + index * 20_000, high: 282_000 },
      certain_profit: -300_000,
      orders_note: null,
      per: "month",
    },
    margin_before_pct: 13.8,
    margin_after_pct: 12.7,
    profit_status: "ok",
    cost_known: true,
    cost: { amount: 300_000, period_days: 14, per_unit: null, label: "Voucher ở mức dùng dự kiến" },
    break_even: { applies: true, extra_orders: 18, period_days: 14, ctor_now: 2.5, ctor_needed: 2.71 },
    basis: { key: "product_history", label: "từ lịch sử sản phẩm", detail: null },
    warnings: [],
    breach: false,
    details: { qualifying_orders: 90, total_orders: 210, voucher_cost_scenario: 300_000 },
    ...over,
  };
}

export const FLOOR_WARNING = { type: "floor", sku: "TZ-D-5", kind: "operating", floor: 131_333, min_unit_price: 129_000 };

export function evaluation(n: number, over: (i: number) => Partial<BuilderOutcome> = () => ({})): BuilderEvaluation {
  const versions = Array.from({ length: n }, (_, i) => outcome(i, over(i)));
  return {
    saved: false,
    best_profit_p50: n - 1,
    today: { as_of: "2026-11-07", gmv_30d: 26_070_000, orders_30d: 210, aov: 124_143, margin_pct: 13.8, spend_per_day: 200_000, spend_cap: 220_000 },
    table: { rows: [] },
    versions,
  };
}

export function exclusionList(): ExclusionList {
  return {
    excluded: [{ item_id: "17820466113", name: "Bình giữ nhiệt inox X", reason: "ngung_ban", reason_label: "Ngừng bán", set_by: "owner", set_at: "2026-10-28T10:15:00" }],
    count: 1,
    reasons: [
      { key: "ngung_ban", label: "Ngừng bán" },
      { key: "qua_tang", label: "Quà tặng" },
      { key: "phan_phoi", label: "Hàng phân phối" },
      { key: "khac", label: "Khác" },
    ],
  };
}

export interface FakeBuilder extends BuilderApi {
  readonly calls: { name: string; args: unknown[] }[];
}

type Failures = Partial<Record<keyof BuilderApi, Error>>;

/** Every method resolves with the given payload (or a default); `calls` records name and arguments. */
export function fakeBuilder(
  data: Partial<{
    products: PickerResult;
    variations: VariationList;
    evaluate: BuilderEvaluation | ((v: readonly BuilderVersion[]) => BuilderEvaluation);
    compare: BuilderEvaluation | ((v: readonly BuilderVersion[]) => BuilderEvaluation);
    choose: ChooseResult;
    group: GroupResult;
  }> = {},
  failWith: Failures = {},
): FakeBuilder {
  const calls: { name: string; args: unknown[] }[] = [];
  const run = <T,>(name: keyof BuilderApi, value: T, ...args: unknown[]): Promise<T> => {
    calls.push({ name, args });
    const err = failWith[name];
    return err ? Promise.reject(err) : Promise.resolve(value);
  };
  const pick = (f: BuilderEvaluation | ((v: readonly BuilderVersion[]) => BuilderEvaluation) | undefined, v: readonly BuilderVersion[]) => (typeof f === "function" ? f(v) : (f ?? evaluation(v.length)));
  return {
    calls,
    products: (...a) => run("products", data.products ?? pickerProducts(), ...a),
    variations: (id) => run("variations", data.variations ?? variationList(id), id),
    coPurchase: (id) => run("coPurchase", coPurchase(), id),
    adsCampaigns: () =>
      run("adsCampaigns", {
        daily_cap: 220_000,
        campaigns: [{ campaign_key: "c1", name: "GMV Max · Túi zip", running: true, daily_budget: 150_000, roas_target: 6, spend_per_day: 140_000, roas_direct: 6.3, break_even_roas: 4.1, products: [{ item_id: P_ZIP, name: "Túi zip thực phẩm D", spend: 1, roas_direct: 6.3, break_even_roas: 4.1, below_break_even: false }] }],
      }),
    keywords: (id) => run("keywords", keywordTable(), id),
    evaluate: (v) => run("evaluate", pick(data.evaluate, v), v),
    compare: (v) => run("compare", pick(data.compare, v), v),
    choose: (b) => run("choose", data.choose ?? { id: "card-1", code: "JC-2611-0021", status: "sent", origin: "manual", position: 1, versions: [] }, b),
    group: (b) =>
      run(
        "group",
        data.group ?? ({ plan: null, cards: [], aggregate: null, groups: [], windows: null, change_sets: [], saved: b.members.map((i) => ({ id: `card-${i + 1}`, code: `JC-2611-00${i + 1}`, indexes: [i] })), placed: [] } as GroupResult),
        b,
      ),
    draftTitle: (b) =>
      run("draftTitle", { item_id: b.itemId, max_chars: 100, drafts: [{ title: "Túi Zip Thực Phẩm, Túi Zip Đựng Đồ Ăn Combo 3 Hộp", chars: 47, keywords: { covered: ["túi zip thực phẩm"], missing: [] } }] }, b),
    draftCover: (b) => run("draftCover", { concepts: [{ overlay: { layout: "banner_bottom", price_vnd: 25_900, pack_text: "25.900đ / hộp", hook_text: "Combo 10 hộp" }, rationale: "giá mỗi hộp" }], note: "Ảnh thật giữ nguyên; chỉ thêm chữ." }, b),
    draftDescription: (b) => run("draftDescription", { drafts: [{ first_line: "Chỉ 25.900đ mỗi hộp khi mua Combo 10 hộp.", chars: 40 }], max_chars: 500 }, b),
    exclusions: () => run("exclusions", exclusionList()),
    exclude: (id, reason, note) => run("exclude", { ...exclusionList().excluded[0]!, item_id: id, reason }, id, reason, note),
    undoExclusion: (id, note) => run("undoExclusion", undefined, id, note),
  };
}
