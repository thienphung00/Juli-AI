import { configure, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import { FLOOR_WARNING, P_IDLE, P_SPONGE, P_ZIP, evaluation, fakeBuilder, type FakeBuilder } from "../../../lib/shopee-decisions/__tests__/builder-fixtures";
import { fakeReco } from "../../../lib/shopee-decisions/__tests__/fixtures";
import { BuilderP92View } from "../builder-p92";
import { renderReco } from "./harness";

// The evaluation is debounced; a loaded machine needs more than the default second.
configure({ asyncUtilTimeout: 4000 });

function open(builder: FakeBuilder = fakeBuilder(), productId: string | null = null, over = {}) {
  return { builder, ...renderReco(<BuilderP92View from="quyet-dinh" productId={productId} />, fakeReco(), { builder, ...over }) };
}

const calls = (b: FakeBuilder, name: string) => b.calls.filter((c) => c.name === name);
const lastVersions = (b: FakeBuilder, name: string) => calls(b, name).at(-1)!.args[0] as Record<string, unknown>[];

async function toKinds(builder: FakeBuilder) {
  fireEvent.click(await screen.findByTestId(`p2-prod-${P_ZIP}`));
  fireEvent.click(await screen.findByTestId("p2-vnext"));
  await screen.findByTestId("p2-kinds");
  return builder;
}

async function addVoucher(builder: FakeBuilder, value: string, min: string) {
  fireEvent.click(screen.getByTestId("p2-kind-voucher"));
  fireEvent.change(await screen.findByRole("textbox", { name: "Giá trị" }), { target: { value } });
  fireEvent.change(screen.getByRole("textbox", { name: "Đơn tối thiểu" }), { target: { value: min } });
  await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "voucher", value: Number(value), min_spend: Number(min) }));
  await waitFor(() => expect(screen.getByTestId("p2-add")).toBeEnabled());
  fireEvent.click(screen.getByTestId("p2-add"));
  await screen.findByTestId("p2-kinds");
}

afterEach(() => {
  // @ts-expect-error jsdom has no matchMedia unless a test defines it
  delete window.matchMedia;
});

describe("P92 · chọn sản phẩm và phân loại", () => {
  it("lists every active listing, also those without orders in the last 30 days, with the missing-cost chips", async () => {
    open();
    expect(await screen.findByTestId("p2-picker-count")).toHaveTextContent("12 sản phẩm đang bán · xếp theo GMV 90 ngày");
    const idle = screen.getByTestId(`p2-prod-${P_IDLE}`);
    expect(idle).toHaveTextContent("không bán 30 ngày qua");
    expect(idle).toHaveTextContent("thiếu giá vốn");
    expect(screen.getByRole("button", { name: "Thiếu giá vốn 2" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Không bán 30 ngày qua 1" })).toBeInTheDocument();
    expect(screen.getByTestId("p2-picker-foot")).toHaveTextContent("Hiện 9 trong 12 sản phẩm đang bán");
    fireEvent.click(screen.getByRole("button", { name: /Xem thêm 3 sản phẩm/ }));
    expect(screen.getAllByTestId(/^p2-prod-/)).toHaveLength(12);
    expect(screen.getByTestId("p2-excluded-note")).toHaveTextContent("Đã loại trừ 4 sản phẩm");
  });

  it("searches by name or id and filters", async () => {
    open();
    fireEvent.change(await screen.findByLabelText("Tìm sản phẩm theo tên hoặc mã"), { target: { value: "màng" } });
    expect(screen.getAllByTestId(/^p2-prod-/)).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("Tìm sản phẩm theo tên hoặc mã"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Thiếu giá vốn 2" }));
    expect(screen.getAllByTestId(/^p2-prod-/)).toHaveLength(2);
  });

  it("a product opened from its page skips to the variation picker; 'So sánh phân loại' shows price and margin only", async () => {
    open(fakeBuilder(), P_ZIP);
    expect(await screen.findByTestId("p2-vstep")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Combo 3 hộp/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByTestId("p2-vcmp")).toBeNull();
    fireEvent.click(screen.getByTestId("p2-vcmp-toggle"));
    const table = await screen.findByTestId("p2-vcmp");
    expect(within(table).getByTestId("p2-vcmp-v3")).toHaveTextContent("99.000đ");
    expect(within(table).getByTestId("p2-vcmp-v3")).toHaveTextContent("87.000đ");
    expect(within(table).getByTestId("p2-vcmp-v3")).toHaveTextContent("29.000đ/đơn vị");
    expect(within(table).getByTestId("p2-vcmp-v3")).toHaveTextContent("16,0%");
    expect(within(table).getByTestId("p2-vcmp-v10")).toHaveTextContent("chưa tính");
    expect(table).toHaveTextContent("mọi chỉ số khác (lượt xem, CTR, CTOR, đơn, AOV) là của cả sản phẩm");
  });
});

describe("P92 · voucher 5k/100k và 10k/100k", () => {
  it("sends typed numbers (no sliders), shows the result block, and compares two vouchers side by side", async () => {
    const builder = fakeBuilder({ compare: (v) => evaluation(v.length) });
    open(builder);
    await toKinds(builder);
    await addVoucher(builder, "5000", "100000");
    const first = lastVersions(builder, "evaluate")[0]!;
    expect(first).toMatchObject({ kind: "voucher", scope: "product", item_ids: [P_ZIP], discount_type: "amount", value: 5000, min_spend: 100000, label: "5k / 100k" });
    await addVoucher(builder, "10000", "100000");
    fireEvent.click(screen.getByTestId("p2-open-compare"));
    await screen.findByTestId("p2-cmp-table");
    expect(lastVersions(builder, "compare")).toHaveLength(2);
    expect(lastVersions(builder, "compare").map((v) => v["value"])).toEqual([5000, 10000]);
    expect(screen.getByTestId("p2-dgmv-1")).toHaveTextContent("+2.714.000đ");
    expect(screen.getByTestId("p2-row-dgmv")).toHaveTextContent("+2.714.000đ");
    expect(screen.getByTestId("p2-row-breakeven")).toHaveTextContent("cần thêm ≥ 18 đơn, tức CTOR ≥ 2,71% (hôm nay 2,50%), để lợi nhuận không giảm.");
    expect(screen.getByTestId("p2-row-drivers")).toHaveTextContent("CTOR");
    expect(screen.getByTestId("p2-row-basis")).toHaveTextContent("từ lịch sử sản phẩm");
  });

  it("chips from the shop AOV fill the value and minimum", async () => {
    const builder = fakeBuilder();
    open(builder);
    await toKinds(builder);
    fireEvent.click(screen.getByTestId("p2-kind-voucher"));
    await screen.findByTestId("p2-panel-voucher");
    await waitFor(() => expect(calls(builder, "evaluate").length).toBeGreaterThan(0));
    await screen.findByText("Gợi ý từ AOV của shop (124.143đ)");
    fireEvent.click(screen.getByRole("button", { name: "10k / 150k" }));
    expect(screen.getByRole("textbox", { name: "Giá trị" })).toHaveValue("10000");
    expect(screen.getByRole("textbox", { name: "Đơn tối thiểu" })).toHaveValue("150000");
  });

  it("the result block names the driver metrics with CTOR, the basis and the break-even", async () => {
    const builder = fakeBuilder();
    open(builder);
    await toKinds(builder);
    fireEvent.click(screen.getByTestId("p2-kind-voucher"));
    const block = await screen.findByTestId("p2-result");
    await waitFor(() => expect(within(block).getByTestId("p2-drivers")).toHaveTextContent("CTOR2,50% → 2,69%"));
    expect(within(block).getByTestId("p2-drivers")).toHaveTextContent("AOV124.143đ → 127.364đ");
    expect(within(block).getByTestId("p2-dprofit")).toHaveTextContent("+54.000đ");
    expect(within(block).getByTestId("p2-dprofit")).toHaveTextContent("−157.000đ – +282.000đ");
    expect(within(block).getByTestId("p2-margin")).toHaveTextContent("12,7%");
    expect(within(block).getByTestId("p2-basis")).toHaveTextContent("từ lịch sử sản phẩm");
    expect(screen.getByTestId("p2-voucher-qualify")).toHaveTextContent("90 / 210 đơn (43%) của 30 ngày qua có giá trị từ 100.000đ trở lên");
  });
});

describe("P92 · chưa tính, không đủ dữ liệu", () => {
  it("a listing without giá vốn reads 'chưa tính' with the link to Thông số shop; insufficient basis prints dashes", async () => {
    const builder = fakeBuilder({
      evaluate: evaluation(1, () => ({
        profit_status: "chua_tinh",
        cost_known: false,
        margin_after_pct: null,
        delta: { gmv: { low: 1, p50: 2, high: 3 }, orders: { low: 0, p50: 1, high: 2 }, profit: null },
        basis: { key: "insufficient", label: "không đủ dữ liệu" },
        warnings: [{ type: "cost_unknown" }],
      })),
    });
    open(builder);
    await toKinds(builder);
    fireEvent.click(screen.getByTestId("p2-kind-voucher"));
    const profit = await screen.findByTestId("p2-dprofit");
    await waitFor(() => expect(profit).toHaveTextContent("chưa tính"));
    expect(within(profit).getByRole("link", { name: "Cài đặt › Thông số shop" })).toHaveAttribute("href", expect.stringContaining("thong-so-shop"));
    expect(screen.getByTestId("p2-margin")).toHaveTextContent("chưa tính");
    expect(screen.getByTestId("p2-basis")).toHaveTextContent("không đủ dữ liệu");
  });
});

describe("P92 · chọn phương án", () => {
  async function twoVersions(builder: FakeBuilder) {
    open(builder);
    await toKinds(builder);
    await addVoucher(builder, "5000", "100000");
    await addVoucher(builder, "10000", "100000");
    fireEvent.click(screen.getByTestId("p2-open-compare"));
    await screen.findByTestId("p2-cmp-table");
  }

  it("a breach opens the P91 warning; 'Quay lại' chooses nothing; 'Vẫn tiếp tục' chooses with acknowledge_breaches", async () => {
    const builder = fakeBuilder({ compare: (v) => evaluation(v.length, (i) => (i === 1 ? { warnings: [FLOOR_WARNING], breach: true } : {})) });
    await twoVersions(builder);
    expect(screen.getByTestId("p2-warn-2")).toHaveTextContent("Chạm giá sàn");
    expect(screen.getByTestId("p2-warn-1")).toHaveTextContent("Trên giá sàn");
    fireEvent.click(screen.getByTestId("p2-choose-2"));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByRole("heading")).toHaveTextContent("Chọn P2 dù chạm giá sàn?");
    fireEvent.click(within(dialog).getByRole("button", { name: "Quay lại" }));
    expect(calls(builder, "choose")).toHaveLength(0);
    fireEvent.click(screen.getByTestId("p2-choose-2"));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Vẫn tiếp tục" }));
    const done = await screen.findByTestId("p2-chosen");
    const body = calls(builder, "choose")[0]!.args[0] as { chosen: number; acknowledgeBreaches: boolean; versions: unknown[] };
    expect(body).toMatchObject({ chosen: 1, acknowledgeBreaches: true });
    expect(body.versions).toHaveLength(2);
    expect(done).toHaveTextContent("Đã chuyển P2 sang Quyết định · thẻ thủ công JC-2611-0021 · nguồn: thủ công");
    expect(screen.getByTestId("p2-ack")).toHaveTextContent(/Đã xác nhận vượt giá sàn · \d{2}\/\d{2}\/\d{4} \d{2}:\d{2}/);
  });

  it("without a breach it chooses straight away; a server 422 reco_breach_not_acknowledged opens the same warning and re-sends", async () => {
    const builder = fakeBuilder({ compare: (v) => evaluation(v.length) });
    const real = builder.choose.bind(builder);
    let first = true;
    builder.choose = (b) => {
      if (first) {
        first = false;
        builder.calls.push({ name: "choose", args: [b] });
        return Promise.reject(new ShopeeApiError(422, "reco_breach_not_acknowledged", "ack", { code: "reco_breach_not_acknowledged", breaches: [{ type: "floor", sku: "S1", kind: "operating", floor: 100000, min_unit_price: 90000 }] }));
      }
      return real(b);
    };
    await twoVersions(builder);
    fireEvent.click(screen.getByTestId("p2-choose-1"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Giá sàn: S1, khách trả 90.000đ thấp hơn sàn vận hành 100.000đ, thiếu 10.000đ (chưa lỗ).");
    fireEvent.click(within(dialog).getByRole("button", { name: "Vẫn tiếp tục" }));
    await screen.findByTestId("p2-chosen");
    const sent = calls(builder, "choose").map((c) => (c.args[0] as { acknowledgeBreaches: boolean }).acknowledgeBreaches);
    expect(sent).toEqual([false, true]);
  });

  it("Ops 'Xem như shop' is read-only: Chọn is disabled", async () => {
    const builder = fakeBuilder({ compare: (v) => evaluation(v.length) });
    open(builder, null, { readOnly: true });
    await toKinds(builder);
    await addVoucher(builder, "5000", "100000");
    await addVoucher(builder, "10000", "100000");
    fireEvent.click(screen.getByTestId("p2-open-compare"));
    await screen.findByTestId("p2-cmp-table");
    expect(screen.getByTestId("p2-choose-1")).toBeDisabled();
  });

  it("a refused version says why and cannot be chosen", async () => {
    const builder = fakeBuilder({ compare: (v) => evaluation(v.length, (i) => (i === 1 ? { ok: false, refusal: { code: "x", message: "Các sản phẩm trong combo phải khác nhau." } } : {})) });
    await twoVersions(builder);
    expect(screen.getByTestId("p2-cost-2")).toHaveTextContent("Các sản phẩm trong combo phải khác nhau.");
    expect(screen.getByTestId("p2-choose-2")).toBeDisabled();
  });
});

describe("P92 · các loại khác", () => {
  it("title: ticked keywords go to the LLM; 'LLM tắt' keeps manual editing with the 100-character counter and coverage", async () => {
    const builder = fakeBuilder({}, { draftTitle: new ShopeeApiError(503, "llm_off", "LLM tắt") });
    open(builder);
    await toKinds(builder);
    fireEvent.click(screen.getByTestId("p2-kind-title"));
    await screen.findByTestId("p2-kw-table");
    fireEvent.click(screen.getByRole("checkbox", { name: "Chọn từ khoá túi zip đựng đồ ăn" }));
    fireEvent.click(screen.getByTestId("p2-title-draft"));
    expect(await screen.findByTestId("p2-llm-off")).toHaveTextContent("LLM tắt");
    expect((calls(builder, "draftTitle")[0]!.args[0] as { keywords: string[] }).keywords).toEqual(["túi zip đựng đồ ăn"]);
    const box = screen.getByRole("textbox", { name: "Tiêu đề" });
    fireEvent.change(box, { target: { value: "x".repeat(104) } });
    expect(screen.getByTestId("p2-title-count")).toHaveTextContent("104/100");
    expect(screen.getByText("Quá 4 ký tự: không thêm được.")).toBeInTheDocument();
    expect(screen.getByText(/✕ túi zip đựng đồ ăn/)).toBeInTheDocument();
    fireEvent.change(box, { target: { value: "Túi Zip Đựng Đồ Ăn 20 túi" } });
    expect(screen.getByText(/✓ túi zip đựng đồ ăn/)).toBeInTheDocument();
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "title", item_id: P_ZIP, title: "Túi Zip Đựng Đồ Ăn 20 túi", keywords: ["túi zip đựng đồ ăn"] }));
  });

  it("title drafts from the LLM can be taken, with their coverage", async () => {
    const builder = fakeBuilder();
    open(builder);
    await toKinds(builder);
    fireEvent.click(screen.getByTestId("p2-kind-title"));
    await screen.findByTestId("p2-kw-table");
    fireEvent.click(screen.getByRole("checkbox", { name: "Chọn từ khoá túi zip thực phẩm" }));
    fireEvent.click(screen.getByTestId("p2-title-draft"));
    const drafts = await screen.findByTestId("p2-title-drafts");
    expect(drafts).toHaveTextContent("phủ 1/1 từ khoá đã chọn");
    fireEvent.click(within(drafts).getByRole("button", { name: "Dùng" }));
    expect(screen.getByRole("textbox", { name: "Tiêu đề" })).toHaveValue("Túi Zip Thực Phẩm, Túi Zip Đựng Đồ Ăn Combo 3 Hộp");
  });

  it("combo: 2–6 products with co-purchase suggestions, sent with pricing and target", async () => {
    const builder = fakeBuilder();
    open(builder);
    await toKinds(builder);
    fireEvent.click(screen.getByTestId("p2-kind-combo"));
    const suggest = await screen.findByTestId("p2-copurchase");
    await waitFor(() => expect(suggest).toHaveTextContent("Miếng rửa chén C"));
    expect(suggest).toHaveTextContent("41 lần");
    fireEvent.click(within(suggest).getByRole("button", { name: "Bắt đầu ›" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Mức giảm" }), { target: { value: "20" } });
    await waitFor(() => {
      const v = lastVersions(builder, "evaluate")[0] as { kind: string; items: { item_id: string }[]; pricing: string; value: number; target: string };
      expect(v).toMatchObject({ kind: "combo", pricing: "pct", value: 20, target: "new_listing" });
      expect(v.items.map((i) => i.item_id)).toEqual([P_ZIP, P_SPONGE]);
    });
    fireEvent.click(screen.getByRole("button", { name: "+ Thêm sản phẩm (tối đa 6)" }));
    expect(screen.getAllByRole("combobox", { name: /^Sản phẩm \d$/ })).toHaveLength(3);
  });

  it("gift: 'quà không bán' takes a typed cost and a min-spend trigger", async () => {
    const builder = fakeBuilder();
    open(builder);
    await toKinds(builder);
    fireEvent.click(screen.getByTestId("p2-kind-gift"));
    fireEvent.click(await screen.findByRole("button", { name: "Quà không bán" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Chi phí mỗi quà" }), { target: { value: "6500" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Quà không bán · tên" }), { target: { value: "Móc dán tường" } });
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "gift", gift: { unit_cost: 6500, qty: 1, label: "Móc dán tường" }, trigger: { type: "min_spend", amount: 150000 } }));
  });

  it("giảm giá: one input per chosen variation; flash sale adds slot and units", async () => {
    const builder = fakeBuilder();
    open(builder);
    await toKinds(builder);
    fireEvent.click(screen.getByTestId("p2-kind-product_discount"));
    fireEvent.change(await screen.findByRole("textbox", { name: "Giảm · Combo 3 hộp" }), { target: { value: "8" } });
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "product_discount", item_id: P_ZIP, variations: [{ variation_id: "v3", discount_pct: 8 }] }));
    fireEvent.click(screen.getByRole("button", { name: "+ Thêm vào So sánh phương án" }));
    fireEvent.click(screen.getByTestId("p2-kind-price_flash"));
    fireEvent.click(await screen.findByRole("radio", { name: "Flash sale của shop" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Giảm · Combo 3 hộp" }), { target: { value: "13" } });
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "flash_sale", units: 50, slot_hours: 2 }));
  });

  it("cover: overlay concepts are text over the real photo; picking one sends the overlay; 'LLM tắt' is said", async () => {
    const builder = fakeBuilder();
    open(builder);
    await toKinds(builder);
    fireEvent.click(screen.getByTestId("p2-kind-cover_image"));
    fireEvent.click(await screen.findByTestId("p2-cover-draft"));
    const concepts = await screen.findByTestId("p2-concepts");
    expect(within(concepts).getByTestId("p2-cover-preview")).toHaveTextContent("ảnh thật, giữ nguyên");
    expect(within(concepts).getByTestId("p2-cover-preview")).toHaveTextContent("25.900đ");
    fireEvent.click(within(concepts).getByRole("button", { name: "Chọn A" }));
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "cover_image", overlay: { layout: "banner_bottom", price_vnd: 25900 } }));
  });

  it("description: first-line drafts, off-switch message and the 300 limit", async () => {
    const builder = fakeBuilder({}, { draftDescription: new ShopeeApiError(503, "llm_off", "LLM tắt") });
    open(builder);
    await toKinds(builder);
    fireEvent.click(screen.getByTestId("p2-kind-description_first_line"));
    fireEvent.click(await screen.findByTestId("p2-desc-draft"));
    expect(await screen.findByTestId("p2-llm-off")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Dòng đầu mô tả" }), { target: { value: "Chỉ 25.900đ mỗi hộp" } });
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "description_first_line", first_line: "Chỉ 25.900đ mỗi hộp" }));
  });

  it("ads, affiliate, variation set and price display build their versions", async () => {
    const builder = fakeBuilder();
    open(builder);
    await toKinds(builder);
    fireEvent.click(screen.getByTestId("p2-kind-ads"));
    await screen.findByTestId("p2-panel-ads");
    await waitFor(() => expect(calls(builder, "adsCampaigns")).toHaveLength(1));
    fireEvent.change(await screen.findByRole("combobox", { name: "Chiến dịch" }), { target: { value: "c1" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Ngân sách mới mỗi ngày" }), { target: { value: "200000" } });
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "ads", lever: "budget", campaign_key: "c1", daily_budget: 200000 }));
    fireEvent.click(screen.getByTestId("p2-add"));
    fireEvent.click(await screen.findByTestId("p2-kind-affiliate"));
    fireEvent.change(await screen.findByRole("textbox", { name: "Số mẫu gửi" }), { target: { value: "3" } });
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "affiliate", commission_pct: 10, sample_qty: 3 }));
    fireEvent.click(screen.getByRole("button", { name: "Đặt lại" }));
    fireEvent.click(screen.getByRole("button", { name: /Chọn loại chiến lược/ }));
    fireEvent.click(screen.getByTestId("p2-kind-variation_set"));
    fireEvent.change(await screen.findByRole("textbox", { name: "Tên phân loại 1" }), { target: { value: "Set 7 hộp" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Giá 1" }), { target: { value: "189000" } });
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "variation_set", item_id: P_ZIP, new_variations: [{ name: "Set 7 hộp", price: 189000 }] }));
    fireEvent.click(screen.getByRole("button", { name: /Chọn loại chiến lược/ }));
    fireEvent.click(screen.getByTestId("p2-kind-price_display"));
    fireEvent.click(await screen.findByRole("radio", { name: "Ẩn listing" }));
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "listing_hide", item_id: P_ZIP }));
  });

  it("a fifth version cannot be added", async () => {
    const builder = fakeBuilder();
    open(builder);
    await toKinds(builder);
    for (const v of ["1000", "2000", "3000", "4000"]) await addVoucher(builder, v, "100000");
    expect(screen.getByTestId("p2-open-compare")).toHaveTextContent("(4/4)");
    fireEvent.click(screen.getByTestId("p2-kind-voucher"));
    await screen.findByTestId("p2-panel-voucher");
    expect(screen.getByText("Đã đủ 4 phương án: sửa hoặc xoá một phương án để thêm.")).toBeInTheDocument();
  });

  it("an evaluate error is shown in the result block", async () => {
    const builder = fakeBuilder({}, { evaluate: new ShopeeApiError(409, "reco_no_data", "Chưa có số liệu Shopee.") });
    open(builder);
    await toKinds(builder);
    fireEvent.click(screen.getByTestId("p2-kind-voucher"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Chưa có số liệu Shopee.");
  });
});

describe("P92 · trên điện thoại", () => {
  it("compares as swipe cards and the warning is a bottom sheet", async () => {
    window.matchMedia = ((query: string) => ({ matches: true, media: query, addEventListener: () => undefined, removeEventListener: () => undefined })) as unknown as typeof window.matchMedia;
    const builder = fakeBuilder({ compare: (v) => evaluation(v.length, (i) => (i === 1 ? { warnings: [FLOOR_WARNING], breach: true } : {})) });
    open(builder);
    expect(await screen.findByText("Mọi sản phẩm đang bán đều chọn được, không chỉ sản phẩm có đơn 30 ngày qua.")).toBeInTheDocument();
    await toKinds(builder);
    await addVoucher(builder, "5000", "100000");
    await addVoucher(builder, "10000", "100000");
    fireEvent.click(screen.getByTestId("p2-open-compare"));
    const swipe = await screen.findByTestId("p2-swipe");
    expect(screen.queryByTestId("p2-cmp-table")).toBeNull();
    expect(within(swipe).getAllByText(/^P\d$/)).toHaveLength(2);
    fireEvent.click(screen.getByTestId("p2-choose-2"));
    expect((await screen.findByRole("alertdialog")).className).toContain("sv-warn--sheet");
  });
});
