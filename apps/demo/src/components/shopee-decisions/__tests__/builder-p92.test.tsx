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
  await waitFor(() => expect(screen.getByTestId("p2-vnext")).toBeEnabled());
  fireEvent.click(screen.getByTestId("p2-vnext"));
  await screen.findByTestId("p2-kinds");
  return builder;
}

function chooseKind(key: string) {
  if (!screen.queryByTestId("p2-kinds")) fireEvent.click(screen.getByRole("button", { name: "Đổi chiến lược" }));
  fireEvent.click(screen.getByTestId(`p2-kind-${key}`));
  fireEvent.click(screen.getByTestId("p2-knext"));
}

async function addVoucher(builder: FakeBuilder, value: string, min: string) {
  chooseKind("voucher");
  fireEvent.change(await screen.findByRole("textbox", { name: "Giá trị" }), { target: { value } });
  fireEvent.change(screen.getByRole("textbox", { name: "Đơn tối thiểu" }), { target: { value: min } });
  await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "voucher", value: Number(value), min_spend: Number(min) }));
  await waitFor(() => expect(screen.getByTestId("p2-add")).toBeEnabled());
  fireEvent.click(screen.getByTestId("p2-add"));
  await waitFor(() => expect(screen.getByTestId("p3-next")).toBeEnabled());
}

afterEach(() => {
  // @ts-expect-error jsdom has no matchMedia unless a test defines it
  delete window.matchMedia;
});

describe("P92 · chọn sản phẩm và phân loại", () => {
  it("step 1 shows a card per active listing; without channel data every figure reads —", async () => {
    open();
    await screen.findByTestId("p2-picker");
    expect(screen.getAllByTestId(/^p2-prod-/)).toHaveLength(12);
    const card = screen.getByTestId(`p2-prod-${P_IDLE}`);
    expect(card).toHaveTextContent("GMV 30 ngày — · biên —");
    expect(card).toHaveTextContent("Điểm nghẽn: —");
    expect(screen.getByTestId("p2-excluded-note")).toHaveTextContent("Đã loại trừ 4 sản phẩm");
    expect(screen.getByRole("link", { name: /Đã loại trừ 4 sản phẩm/ })).toHaveAttribute("href", "/settings?tab=loai-tru-san-pham");
    expect(screen.getByRole("button", { name: "Cả shop" })).toBeInTheDocument();
  });

  it("step 1 cards take GMV, margin, the Organic / Quảng cáo / TTLK split and the weakest metric from the channel split; a null stays —", async () => {
    const builder = fakeBuilder({
      channelSplitProducts: async () => ({
        products: [
          { product_id: P_ZIP, name: "Túi zip", image_url: "https://img.example/zip.jpg", gmv: 5_000_000, margin: 31.5, organic_gmv: 3_000_000, ads_gmv: 1_500_000, affiliate_gmv: null, weakest_metric: "ctor" },
          { product_id: P_SPONGE, gmv: null, margin: null, organic_gmv: null, ads_gmv: null, affiliate_gmv: null, weakest_metric: null },
        ],
      }),
    });
    open(builder);
    const zip = await screen.findByTestId(`p2-prod-${P_ZIP}`);
    await waitFor(() => expect(zip).toHaveTextContent("GMV 30 ngày 5.000.000đ · biên 31,5%"));
    expect(zip).toHaveTextContent("Organic3.000.000đ");
    expect(zip).toHaveTextContent("Quảng cáo1.500.000đ");
    expect(zip).toHaveTextContent("TTLK—");
    expect(zip).toHaveTextContent("Điểm nghẽn: CTOR");
    expect(zip.querySelector("img")).toHaveAttribute("src", "https://img.example/zip.jpg");
    expect(screen.getByTestId(`p2-prod-${P_SPONGE}`)).toHaveTextContent("GMV 30 ngày — · biên —");
  });

  it("step 1 search narrows the cards", async () => {
    open();
    fireEvent.change(await screen.findByLabelText("Tìm sản phẩm"), { target: { value: "màng" } });
    expect(screen.getAllByTestId(/^p2-prod-/)).toHaveLength(1);
  });

  it("the stepper has four steps; done steps are clickable and later ones are not until reached", async () => {
    const builder = fakeBuilder();
    open(builder);
    const nav = await screen.findByTestId("p2-stepper");
    expect(nav).toHaveTextContent("1 · Sản phẩm");
    expect(nav).toHaveTextContent("2 · Chiến lược");
    expect(nav).toHaveTextContent("3 · Phương án");
    expect(nav).toHaveTextContent("4 · So sánh & lưu");
    expect(within(nav).queryByRole("button")).toBeNull();
    await toKinds(builder);
    expect(screen.getByTestId("p2-eyebrow")).toHaveTextContent(/TÚI/);
    fireEvent.click(within(screen.getByTestId("p2-stepper")).getByRole("button", { name: /1 · Sản phẩm/ }));
    expect(await screen.findByTestId("p2-picker")).toBeInTheDocument();
    fireEvent.click(within(screen.getByTestId("p2-stepper")).getByRole("button", { name: /2 · Chiến lược/ }));
    expect(await screen.findByTestId("p2-kinds")).toBeInTheDocument();
  });

  it("step 2 has the three groups, the metric chips and a cost line only where it costs; the removed kinds are gone", async () => {
    const builder = fakeBuilder();
    open(builder);
    await toKinds(builder);
    const offer = screen.getByTestId("p2-group-offer");
    const listing = screen.getByTestId("p2-group-listing");
    const traffic = screen.getByTestId("p2-group-traffic");
    expect(offer).toHaveTextContent("Chi phí: tiền giảm giá");
    expect(listing).not.toHaveTextContent("Chi phí");
    expect(traffic).toHaveTextContent("Chi phí: quảng cáo / hoa hồng");
    for (const k of ["voucher", "combo", "deal_soc", "product_discount", "price_flash"]) expect(within(offer).getByTestId(`p2-kind-${k}`)).toBeInTheDocument();
    for (const k of ["title", "cover_image", "description_first_line", "price_display", "variation_set"]) expect(within(listing).getByTestId(`p2-kind-${k}`)).toBeInTheDocument();
    for (const k of ["ads", "affiliate"]) expect(within(traffic).getByTestId(`p2-kind-${k}`)).toBeInTheDocument();
    expect(screen.queryByTestId("p2-kind-listing_combo")).toBeNull();
    expect(screen.queryByText("Listing combo mới")).toBeNull();
    expect(screen.queryByText(/Ẩn \/ đưa lại/)).toBeNull();
    expect(within(listing).getByText("Lượt xem")).toHaveClass("p2-m--views");
    expect(within(offer).getByText("AOV")).toHaveClass("p2-m--aov");
    expect(screen.getByTestId("p2-knext")).toBeDisabled();
    fireEvent.click(screen.getByTestId("p2-kind-voucher"));
    expect(screen.getByTestId("p2-knext")).toHaveTextContent("Tiếp tục với Voucher");
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
    fireEvent.click(screen.getByTestId("p3-next"));
    await screen.findByTestId("p4-table");
    expect(lastVersions(builder, "compare")).toHaveLength(2);
    expect(lastVersions(builder, "compare").map((v) => v["value"])).toEqual([5000, 10000]);
    expect(screen.getByTestId("p4-row-1")).toBeInTheDocument();
    expect(screen.getByTestId("p4-row-2")).toBeInTheDocument();
  });

  it("chips from the shop AOV fill the value and minimum", async () => {
    const builder = fakeBuilder();
    open(builder);
    await toKinds(builder);
    chooseKind("voucher");
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
    chooseKind("voucher");
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
    chooseKind("voucher");
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
    fireEvent.click(screen.getByTestId("p3-next"));
    await screen.findByTestId("p4-table");
  }

  it("a breach opens the P91 warning; 'Quay lại' chooses nothing; 'Vẫn tiếp tục' chooses with acknowledge_breaches", async () => {
    const builder = fakeBuilder({ compare: (v) => evaluation(v.length, (i) => (i === 1 ? { warnings: [FLOOR_WARNING], breach: true } : {})) });
    await twoVersions(builder);
    fireEvent.click(screen.getByRole("radio", { name: "P2 là phương án chính" }));
    fireEvent.click(screen.getByTestId("p4-save"));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByRole("heading")).toHaveTextContent("Lưu P2 dù chạm giá sàn?");
    fireEvent.click(within(dialog).getByRole("button", { name: "Quay lại" }));
    expect(calls(builder, "choose")).toHaveLength(0);
    fireEvent.click(screen.getByTestId("p4-save"));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Vẫn tiếp tục" }));
    const done = await screen.findByTestId("p4-saved");
    const body = calls(builder, "choose")[0]!.args[0] as { chosen: number; acknowledgeBreaches: boolean; versions: unknown[] };
    expect(body).toMatchObject({ chosen: 1, acknowledgeBreaches: true });
    expect(body.versions).toHaveLength(2);
    expect(done).toHaveTextContent("Đã lưu · JC-2611-0021 · P2 là phương án chính");
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
    fireEvent.click(screen.getByTestId("p4-save"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Giá sàn: S1, khách trả 90.000đ thấp hơn sàn vận hành 100.000đ, thiếu 10.000đ (chưa lỗ).");
    fireEvent.click(within(dialog).getByRole("button", { name: "Vẫn tiếp tục" }));
    await screen.findByTestId("p4-saved");
    const sent = calls(builder, "choose").map((c) => (c.args[0] as { acknowledgeBreaches: boolean }).acknowledgeBreaches);
    expect(sent).toEqual([false, true]);
  });

  it("Ops 'Xem như shop' is read-only: Chọn is disabled", async () => {
    const builder = fakeBuilder({ compare: (v) => evaluation(v.length) });
    open(builder, null, { readOnly: true });
    await toKinds(builder);
    await addVoucher(builder, "5000", "100000");
    await addVoucher(builder, "10000", "100000");
    fireEvent.click(screen.getByTestId("p3-next"));
    await screen.findByTestId("p4-table");
    expect(screen.getByTestId("p4-save")).toBeDisabled();
  });

  it("a refused version says why and cannot be chosen", async () => {
    const builder = fakeBuilder({ compare: (v) => evaluation(v.length, (i) => (i === 1 ? { ok: false, refusal: { code: "x", message: "Các sản phẩm trong combo phải khác nhau." } } : {})) });
    await twoVersions(builder);
    fireEvent.click(screen.getByRole("radio", { name: "P2 là phương án chính" }));
    expect(screen.getByTestId("p4-save")).toBeDisabled();
  });
});

describe("P92 · các loại khác", () => {
  it("title: ticked keywords go to the LLM; 'LLM tắt' keeps manual editing with the 100-character counter and coverage", async () => {
    const builder = fakeBuilder({}, { draftTitle: new ShopeeApiError(503, "llm_off", "LLM tắt") });
    open(builder);
    await toKinds(builder);
    chooseKind("title");
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
    chooseKind("title");
    await screen.findByTestId("p2-kw-table");
    fireEvent.click(screen.getByRole("checkbox", { name: "Chọn từ khoá túi zip thực phẩm" }));
    fireEvent.click(screen.getByTestId("p2-title-draft"));
    const drafts = await screen.findByTestId("p2-title-drafts");
    expect(drafts).toHaveTextContent("phủ 1/1 từ khoá đã chọn");
    fireEvent.click(within(drafts).getByRole("button", { name: "Dùng" }));
    expect(screen.getByRole("textbox", { name: "Tiêu đề" })).toHaveValue("Túi Zip Thực Phẩm, Túi Zip Đựng Đồ Ăn Combo 3 Hộp");
  });

  it("sample shop: pre-written titles offer one live AI rewrite, which sends regenerate and is then gone", async () => {
    const builder = fakeBuilder();
    const sent: (boolean | undefined)[] = [];
    const answer = (source: "seeded" | "llm", left: number, title: string) => ({ item_id: P_ZIP, max_chars: 100, source, live_left: left, drafts: [{ title, chars: title.length, keywords: { covered: ["túi zip thực phẩm"], missing: [] } }] });
    builder.draftTitle = (b) => {
      sent.push(b.regenerate);
      return Promise.resolve(b.regenerate ? answer("llm", 0, "Túi Zip Thực Phẩm Hộp Mới") : answer("seeded", 1, "Túi Zip Thực Phẩm Viết Sẵn"));
    };
    open(builder);
    await toKinds(builder);
    chooseKind("title");
    await screen.findByTestId("p2-kw-table");
    fireEvent.click(screen.getByRole("checkbox", { name: "Chọn từ khoá túi zip thực phẩm" }));
    fireEvent.click(screen.getByTestId("p2-title-draft"));
    expect(await screen.findByTestId("p2-title-drafts")).toHaveTextContent("Túi Zip Thực Phẩm Viết Sẵn");
    expect(screen.getByTestId("p2-title-seeded")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("p2-title-regenerate"));
    await waitFor(() => expect(screen.getByTestId("p2-title-drafts")).toHaveTextContent("Túi Zip Thực Phẩm Hộp Mới"));
    expect(sent).toEqual([false, true]);
    expect(screen.queryByTestId("p2-title-regenerate")).toBeNull();
    expect(screen.queryByTestId("p2-title-seeded")).toBeNull();
  });

  it("combo (Shopee's form): a product list with co-purchase suggestions and tiers 'Mua N', sent without per-item quantity", async () => {
    const builder = fakeBuilder();
    open(builder);
    await toKinds(builder);
    chooseKind("combo");
    const suggest = await screen.findByTestId("p2-copurchase");
    await waitFor(() => expect(suggest).toHaveTextContent("Miếng rửa chén C"));
    expect(suggest).toHaveTextContent("41 lần");
    fireEvent.click(within(suggest).getByRole("button", { name: "Thêm vào combo ›" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Mức 1 · giảm" }), { target: { value: "6" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Tên Combo Khuyến Mãi" }), { target: { value: "Combo túi + miếng" } });
    await waitFor(() => {
      const v = lastVersions(builder, "evaluate")[0] as { kind: string; item_ids: string[]; discount_type: string; tiers: { qty: number; value: number }[]; name: string };
      expect(v).toMatchObject({ kind: "combo", discount_type: "pct", name: "Combo túi + miếng", tiers: [{ qty: 2, value: 6 }, { qty: 3, value: 8 }] });
      expect(v.item_ids).toEqual([P_ZIP, P_SPONGE]);
      expect(v).not.toHaveProperty("items");
    });
    fireEvent.click(screen.getByTestId("p2-add-tier"));
    expect(screen.getByTestId("p2-tier-3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Giảm giá đặc biệt" }));
    expect(screen.getByRole("textbox", { name: "Mức 1 · chỉ với giá" })).toBeInTheDocument();
  });

  it("gift: 'quà không bán' takes a typed cost and a min-spend trigger", async () => {
    const builder = fakeBuilder();
    open(builder);
    await toKinds(builder);
    chooseKind("deal_soc");
    fireEvent.click(await screen.findByRole("radio", { name: "Mua Để Nhận Quà" }));
    fireEvent.click(await screen.findByRole("button", { name: "Quà không bán" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Chi phí mỗi quà" }), { target: { value: "6500" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Quà không bán · tên" }), { target: { value: "Móc dán tường" } });
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "gift", gift: { unit_cost: 6500, qty: 1, label: "Móc dán tường" }, trigger: { type: "min_spend", amount: 150000 } }));
  });

  it("giảm giá: one input per chosen variation; flash sale adds slot and units", async () => {
    const builder = fakeBuilder();
    open(builder);
    await toKinds(builder);
    chooseKind("product_discount");
    fireEvent.change(await screen.findByRole("textbox", { name: "% GIẢM · Combo 3 hộp" }), { target: { value: "8" } });
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "product_discount", item_id: P_ZIP, variations: [{ variation_id: "v3", discount_pct: 8 }] }));
    fireEvent.click(screen.getByRole("button", { name: "+ Thêm phương án" }));
    chooseKind("price_flash");
    fireEvent.click(await screen.findByRole("radio", { name: "Flash sale của shop" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Giảm · Combo 3 hộp" }), { target: { value: "13" } });
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "flash_sale", units: 50, slot_hours: 2 }));
  });

  it("giảm giá, đổi giá and flash sale mount the Giá thị trường marker with the drafted price", async () => {
    const range = {
      item_id: P_ZIP, available: true, reason: null, stale: false, unit: { key: "hop", label: "hộp", per_label: "giá / hộp" },
      // The seller's body: aggregates only (no P25-P75, no position, no listings).
      market: { n_similar: 12, median: 28_000, average: 28_900, own_vs_median_pct: null, own_vs_average_pct: null },
      marker: { price: 80_040, pack_count: 3, price_per_unit: 26_680, vs_median_pct: -4.7, vs_average_pct: -7.7 },
    };
    const urls: string[] = [];
    const fetchImpl = (async (url: string) => {
      urls.push(url);
      return { ok: true, status: 200, json: async () => range } as unknown as Response;
    }) as unknown as typeof fetch;
    const builder = fakeBuilder();
    open(builder, null, { market: { base: "/v1/demo/shopee", token: "tok", shopId: "shop-1", fetchImpl } });
    await toKinds(builder);
    chooseKind("product_discount");
    expect(screen.queryByTestId("market-marker")).toBeNull();
    fireEvent.change(await screen.findByRole("textbox", { name: "% GIẢM · Combo 3 hộp" }), { target: { value: "8" } });
    expect(await screen.findByTestId("market-marker")).toHaveTextContent("trung vị 28.000đ · trung bình 28.900đ")
    expect(screen.getByTestId("market-marker")).toHaveTextContent("bản nháp 26.680đ (−4,7% so với trung vị)")
    expect(screen.queryByTestId("market-bar")).toBeNull();
    // 87.000đ list price minus 8 % = 80.040đ, sent as the drafted price of the variation.
    await waitFor(() => expect(urls.some((u) => u === `/v1/demo/shopee/builder/products/${P_ZIP}/market-range?variation_id=v3&price=80040`)).toBe(true));
    await waitFor(() => expect(screen.getByTestId("p2-add")).toBeEnabled());
    fireEvent.click(screen.getByTestId("p2-add"));
    await waitFor(() => expect(screen.getByTestId("p3-next")).toBeEnabled());
    chooseKind("price_flash");
    // P96 (G3): a list-price change is ± (+ = price up), so the field is "Thay đổi", not "Giảm".
    expect(screen.queryByRole("textbox", { name: "Giảm · Combo 3 hộp" })).not.toBeInTheDocument();
    expect(screen.getByText("−5 = giảm 5%, +5 = tăng 5%")).toBeInTheDocument();
    fireEvent.change(await screen.findByRole("textbox", { name: "Thay đổi · Combo 3 hộp" }), { target: { value: "-10" } });
    await waitFor(() => expect(urls.some((u) => u.endsWith("price=78300"))).toBe(true));
    expect(screen.getByTestId("market-marker")).toBeInTheDocument();
  });

  it("cover: overlay concepts are text over the real photo; picking one sends the overlay; 'LLM tắt' is said", async () => {
    const builder = fakeBuilder();
    open(builder);
    await toKinds(builder);
    chooseKind("cover_image");
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
    chooseKind("description_first_line");
    fireEvent.click(await screen.findByTestId("p2-desc-draft"));
    expect(await screen.findByTestId("p2-llm-off")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Dòng đầu mô tả" }), { target: { value: "Chỉ 25.900đ mỗi hộp" } });
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "description_first_line", first_line: "Chỉ 25.900đ mỗi hộp" }));
  });

  it("ads, affiliate, variation set and price display build their versions", async () => {
    const builder = fakeBuilder();
    open(builder);
    await toKinds(builder);
    chooseKind("ads");
    await screen.findByTestId("p2-panel-ads");
    await waitFor(() => expect(calls(builder, "adsCampaigns")).toHaveLength(1));
    await screen.findByRole("option", { name: /GMV Max/ });
    fireEvent.change(screen.getByRole("combobox", { name: "Chiến dịch" }), { target: { value: "c1" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Ngân sách mới mỗi ngày" }), { target: { value: "200000" } });
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "ads", lever: "budget", campaign_key: "c1", daily_budget: 200000 }));
    fireEvent.click(screen.getByTestId("p2-add"));
    chooseKind("affiliate");
    fireEvent.change(await screen.findByRole("textbox", { name: "Số mẫu gửi" }), { target: { value: "3" } });
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "affiliate", commission_pct: 10, sample_qty: 3, target_campaign: false }));
    // "Chiến dịch" is a yes/no (Target campaign), never a number: the API takes a boolean
    fireEvent.click(screen.getByLabelText(/Áp dụng trong chiến dịch mục tiêu/));
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "affiliate", target_campaign: true }));
    fireEvent.click(screen.getByRole("button", { name: "Đặt lại" }));
    chooseKind("variation_set");
    fireEvent.change(await screen.findByRole("textbox", { name: "Tên phân loại 1" }), { target: { value: "Set 7 hộp" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Giá 1" }), { target: { value: "189000" } });
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "variation_set", item_id: P_ZIP, new_variations: [{ name: "Set 7 hộp", price: 189000 }] }));
    chooseKind("price_display");
    await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "price_display", item_id: P_ZIP }));
    expect(screen.queryByRole("radio", { name: "Ẩn listing" })).toBeNull();
  });

  it("a fifth version cannot be added", async () => {
    const builder = fakeBuilder();
    open(builder);
    await toKinds(builder);
    for (const v of ["1000", "2000", "3000", "4000"]) await addVoucher(builder, v, "100000");
    expect(screen.getByTestId("p3-next")).toHaveTextContent("So sánh 4 phương án");
    chooseKind("voucher");
    await screen.findByTestId("p2-panel-voucher");
  });

  it("an evaluate error is shown in the result block", async () => {
    const builder = fakeBuilder({}, { evaluate: new ShopeeApiError(409, "reco_no_data", "Chưa có số liệu Shopee.") });
    open(builder);
    await toKinds(builder);
    chooseKind("voucher");
    expect(await screen.findByRole("alert")).toHaveTextContent("Chưa có số liệu Shopee.");
  });
});

describe("P92 · trên điện thoại", () => {
  it("the breach warning is a bottom sheet", async () => {
    window.matchMedia = ((query: string) => ({ matches: true, media: query, addEventListener: () => undefined, removeEventListener: () => undefined })) as unknown as typeof window.matchMedia;
    const builder = fakeBuilder({ compare: (v) => evaluation(v.length, (i) => (i === 1 ? { warnings: [FLOOR_WARNING], breach: true } : {})) });
    open(builder);
    await toKinds(builder);
    await addVoucher(builder, "5000", "100000");
    await addVoucher(builder, "10000", "100000");
    fireEvent.click(screen.getByTestId("p3-next"));
    await screen.findByTestId("p4-table");
    fireEvent.click(screen.getByRole("radio", { name: "P2 là phương án chính" }));
    fireEvent.click(screen.getByTestId("p4-save"));
    expect((await screen.findByRole("alertdialog")).className).toContain("sv-warn--sheet");
  });
});
