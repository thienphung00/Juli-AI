import { DASH, fmt, pp, sv, vnd } from "../shopee-analytics/format";
import type { Band, BuilderOutcome, BuilderVersion, BuilderWarning, CoverOverlay, PickerProduct, VariationRow } from "./builder-api";

/**
 * Tự tạo phương án (P92): the form state of each strategy, and how it becomes a version of
 * `POST /builder/evaluate | compare | choose` (`fasttrack/contracts/p92-api.md` §3).
 * Numbers are kept as the raw text of their input and parsed here, so the cursor never jumps.
 */

export type Kind92 =
  | "voucher"
  | "combo"
  | "add_on"
  | "gift"
  | "product_discount"
  | "price_flash"
  | "variation_set"
  | "ads"
  | "title"
  | "cover_image"
  | "description_first_line"
  | "affiliate"
  | "price_display";

export const MAX_VERSIONS = 4;
export const MAX_TITLE = 100;
export const MAX_FIRST_LINE = 300;

/** The 13 strategies, each with the driver metric(s) it is measured by (B-3, artboard `kinds`). */
export const KINDS_92: readonly { readonly key: Kind92; readonly name: string; readonly drivers: string }[] = [
  { key: "voucher", name: "Voucher", drivers: "AOV · CTOR" },
  { key: "combo", name: "Combo nhiều sản phẩm", drivers: "AOV · CTOR" },
  { key: "add_on", name: "Mua kèm", drivers: "AOV" },
  { key: "gift", name: "Quà tặng", drivers: "CTOR · đơn" },
  { key: "product_discount", name: "Giảm giá", drivers: "CTOR · đơn" },
  { key: "price_flash", name: "Giá bán + Flash sale", drivers: "CTOR · đơn" },
  { key: "variation_set", name: "Phân loại / set", drivers: "AOV · CTOR" },
  { key: "ads", name: "Quảng cáo", drivers: "chi · GMV · ROAS" },
  { key: "title", name: "Tiêu đề", drivers: "lượt xem · CTR" },
  { key: "cover_image", name: "Ảnh bìa", drivers: "CTR" },
  { key: "description_first_line", name: "Mô tả", drivers: "CTOR" },
  { key: "affiliate", name: "Affiliate / KOL", drivers: "đơn affiliate" },
  { key: "price_display", name: "Hiển thị giá + listing", drivers: "CTR · CTOR · lượt xem" },
];

export const kindName92 = (k: string): string => KINDS_92.find((x) => x.key === k)?.name ?? k;

/** The kind the server knows for a form kind (some forms hold two). */
export const SERVER_KIND_NAMES: Readonly<Record<string, string>> = {
  voucher: "Voucher",
  combo: "Combo",
  add_on: "Mua kèm",
  gift: "Quà tặng",
  product_discount: "Giảm giá",
  price: "Giá bán",
  flash_sale: "Flash sale",
  variation_set: "Phân loại / set",
  ads: "Quảng cáo",
  title: "Tiêu đề",
  cover_image: "Ảnh bìa",
  description_first_line: "Mô tả",
  affiliate: "Affiliate / KOL",
  price_display: "Hiển thị giá",
  listing_hide: "Ẩn listing",
  listing_relist: "Đưa lại listing",
};

// ── parsing ──────────────────────────────────────────────────────────────

/** A number typed with `.` or `,` as the decimal mark and no grouping; `null` when empty or not a number. */
export function num(text: string | null | undefined): number | null {
  if (text === null || text === undefined) return null;
  const t = text.trim().replace(/\s/g, "").replace(",", ".");
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

/** 5000 -> "5k", 100000 -> "100k", 12500 -> "12.500đ". */
export function kmoney(n: number): string {
  return n % 1000 === 0 && n >= 1000 ? `${fmt(n / 1000)}k` : vnd(n);
}

/** Chips of the voucher panel, from the shop's AOV: 5k/100k, 10k/100k, 10k/150k, 15k/200k at AOV 124.143đ. */
export function voucherChips(aov: number | null): readonly { readonly value: number; readonly min: number; readonly label: string }[] {
  const lo = aov && aov > 0 ? Math.max(50_000, Math.round((aov * 0.8) / 50_000) * 50_000) : 100_000;
  const pairs: [number, number][] = [
    [5_000, lo],
    [10_000, lo],
    [10_000, lo + 50_000],
    [15_000, lo + 100_000],
  ];
  return pairs.map(([value, min]) => ({ value, min, label: `${value / 1000}k / ${min / 1000}k` }));
}

// ── form state ───────────────────────────────────────────────────────────

export interface ComboItem {
  readonly itemId: string;
  readonly variationId: string;
  readonly qty: string;
}
export interface AddonRow {
  readonly itemId: string;
  readonly variationId: string;
  readonly mode: "price" | "pct";
  readonly value: string;
  readonly limit: string;
}
export interface VarValue {
  readonly variationId: string;
  readonly value: string;
}
export interface NewVariation {
  readonly name: string;
  readonly price: string;
  readonly sku: string;
  readonly packCount: string;
  readonly stock: string;
}
export interface KeywordBid {
  readonly keyword: string;
  readonly bid: string;
  readonly match: "broad" | "exact";
}

export interface Forms {
  readonly voucher: { scope: "shop" | "product" | "follower" | "livestream"; dtype: "amount" | "pct"; value: string; min: string; max: string; usage: string; perBuyer: string; start: string; end: string };
  readonly combo: { items: readonly ComboItem[]; pricing: "fixed_price" | "pct" | "amount"; value: string; target: "bundle_deal" | "new_listing" };
  readonly add_on: { addons: readonly AddonRow[] };
  readonly gift: { source: "listing" | "unsold"; giftItemId: string; unitCost: string; label: string; packaging: string; qty: string; trigger: "buy_item" | "min_spend"; triggerItemId: string; minSpend: string };
  readonly product_discount: { mode: "pct" | "final_price"; rows: readonly VarValue[]; start: string; end: string; perBuyer: string };
  readonly price_flash: { what: "price" | "flash_sale"; mode: "pct" | "final_price"; rows: readonly VarValue[]; units: string; slotStart: string; slotHours: string };
  readonly variation_set: { rows: readonly NewVariation[] };
  readonly ads: { lever: "budget" | "roas" | "add_product" | "remove_product" | "keywords"; campaignKey: string; dailyBudget: string; roasTarget: string; itemId: string; keywords: readonly KeywordBid[] };
  readonly title: { ticked: readonly string[]; text: string };
  readonly cover_image: { overlay: CoverOverlay | null };
  readonly description_first_line: { text: string };
  readonly affiliate: { commission: string; campaign: string; samples: string; shipFee: string };
  readonly price_display: { what: "price_display" | "listing_hide" | "listing_relist"; text: string; stock: string };
}

export const newItem = (itemId = "", variationId = ""): ComboItem => ({ itemId, variationId, qty: "1" });

export function initialForms(): Forms {
  return {
    voucher: { scope: "product", dtype: "amount", value: "5000", min: "100000", max: "", usage: "", perBuyer: "", start: "", end: "" },
    combo: { items: [newItem(), newItem()], pricing: "pct", value: "10", target: "new_listing" },
    add_on: { addons: [{ itemId: "", variationId: "", mode: "pct", value: "15", limit: "1" }] },
    gift: { source: "listing", giftItemId: "", unitCost: "", label: "", packaging: "", qty: "1", trigger: "min_spend", triggerItemId: "", minSpend: "150000" },
    product_discount: { mode: "pct", rows: [], start: "", end: "", perBuyer: "" },
    price_flash: { what: "price", mode: "pct", rows: [], units: "50", slotStart: "", slotHours: "2" },
    variation_set: { rows: [{ name: "", price: "", sku: "", packCount: "", stock: "" }] },
    ads: { lever: "budget", campaignKey: "", dailyBudget: "", roasTarget: "", itemId: "", keywords: [{ keyword: "", bid: "", match: "broad" }] },
    title: { ticked: [], text: "" },
    cover_image: { overlay: null },
    description_first_line: { text: "" },
    affiliate: { commission: "10", campaign: "", samples: "0", shipFee: "" },
    price_display: { what: "price_display", text: "", stock: "" },
  };
}

/** What the builder knows about the chosen product when it turns a form into a version. */
export interface BuildCtx {
  readonly product: PickerProduct;
  /** The variations chosen in step 2 (all of them for "Tất cả phân loại"). */
  readonly variations: readonly VariationRow[];
}

export interface Built92 {
  readonly version: BuilderVersion | null;
  /** Why it cannot be priced yet (shown instead of numbers). */
  readonly problem: string | null;
}

const no = (problem: string): Built92 => ({ version: null, problem });
const clip = (s: string, n = 60): string => (s.length > n ? s.slice(0, n) : s);
const dated = (start: string, end: string): Record<string, string> => ({ ...(start ? { start } : {}), ...(end ? { end } : {}) });
const opt = (key: string, text: string): Record<string, number> => {
  const n = num(text);
  return n !== null ? { [key]: n } : {};
};

function varRows(rows: readonly VarValue[], mode: "pct" | "final_price", pctKey: string): { rows: Record<string, unknown>[]; problem: string | null } {
  const out: Record<string, unknown>[] = [];
  for (const r of rows) {
    const n = num(r.value);
    if (n === null || r.value.trim() === "") continue;
    if (n <= 0) return { rows: [], problem: "Nhập số lớn hơn 0." };
    if (mode === "pct" && n >= 100) return { rows: [], problem: "Phần trăm giảm phải nhỏ hơn 100." };
    out.push({ variation_id: r.variationId, [mode === "pct" ? pctKey : "final_price"]: n });
  }
  return { rows: out, problem: out.length === 0 ? "Nhập mức giảm hoặc giá cho ít nhất một phân loại." : null };
}

export function buildVersion(kind: Kind92, f: Forms, ctx: BuildCtx): Built92 {
  const id = ctx.product.item_id;
  switch (kind) {
    case "voucher": {
      const v = f.voucher;
      const value = num(v.value);
      const min = num(v.min) ?? 0;
      if (value === null || value <= 0) return no("Nhập giá trị voucher.");
      if (v.dtype === "pct" && value > 90) return no("Voucher phần trăm tối đa 90%.");
      if (min < 0) return no("Đơn tối thiểu từ 0đ.");
      const label = v.dtype === "pct" ? `${fmt(value, 0)}% / ${kmoney(min)}` : `${kmoney(value)} / ${kmoney(min)}`;
      return {
        problem: null,
        version: {
          kind: "voucher",
          label: clip(label),
          scope: v.scope,
          ...(v.scope === "product" ? { item_ids: [id] } : {}),
          discount_type: v.dtype,
          value,
          min_spend: min,
          ...(v.dtype === "pct" ? opt("max_value", v.max) : {}),
          ...opt("usage_limit", v.usage),
          ...opt("per_buyer_limit", v.perBuyer),
          ...dated(v.start, v.end),
        },
      };
    }
    case "combo": {
      const c = f.combo;
      const items = c.items.filter((i) => i.itemId);
      if (items.length < 2) return no("Combo cần từ 2 đến 6 sản phẩm khác nhau.");
      if (new Set(items.map((i) => i.itemId)).size !== items.length) return no("Các sản phẩm trong combo phải khác nhau.");
      const value = num(c.value);
      if (value === null || value <= 0) return no(c.pricing === "fixed_price" ? "Nhập giá combo." : "Nhập mức giảm.");
      if (c.pricing === "pct" && value >= 100) return no("Phần trăm giảm phải nhỏ hơn 100.");
      const lines = items.map((i) => ({ item_id: i.itemId, variation_id: i.variationId, qty: Math.max(1, Math.min(20, Math.round(num(i.qty) ?? 1))) }));
      return { problem: null, version: { kind: "combo", label: clip(`Combo ${lines.length} sản phẩm`), items: lines, pricing: c.pricing, value, target: c.target } };
    }
    case "add_on": {
      const rows = f.add_on.addons.filter((a) => a.itemId);
      if (rows.length === 0) return no("Chọn ít nhất một sản phẩm mua kèm.");
      const addons: Record<string, unknown>[] = [];
      for (const a of rows) {
        const n = num(a.value);
        if (n === null || n <= 0) return no("Nhập giá mua kèm hoặc % giảm.");
        if (a.mode === "pct" && n >= 100) return no("Phần trăm giảm phải nhỏ hơn 100.");
        addons.push({ item_id: a.itemId, variation_id: a.variationId, [a.mode === "price" ? "price" : "pct"]: n, limit_per_order: Math.max(1, Math.min(20, Math.round(num(a.limit) ?? 1))) });
      }
      return { problem: null, version: { kind: "add_on", label: clip(`Mua kèm ${addons.length} sản phẩm`), main_item_id: id, addons } };
    }
    case "gift": {
      const g = f.gift;
      const qty = Math.max(1, Math.min(20, Math.round(num(g.qty) ?? 1)));
      let gift: Record<string, unknown>;
      if (g.source === "listing") {
        if (!g.giftItemId) return no("Chọn sản phẩm làm quà.");
        gift = { item_id: g.giftItemId, qty, ...opt("packaging", g.packaging) };
      } else {
        const cost = num(g.unitCost);
        if (cost === null || cost < 0) return no("Nhập chi phí mỗi quà.");
        gift = { unit_cost: cost, qty, ...(g.label.trim() ? { label: clip(g.label.trim()) } : {}), ...opt("packaging", g.packaging) };
      }
      let trigger: Record<string, unknown>;
      if (g.trigger === "buy_item") trigger = { type: "buy_item", item_id: g.triggerItemId || id };
      else {
        const amount = num(g.minSpend);
        if (amount === null || amount < 0) return no("Nhập đơn tối thiểu để nhận quà.");
        trigger = { type: "min_spend", amount };
      }
      return { problem: null, version: { kind: "gift", label: clip(g.trigger === "min_spend" ? `Quà đơn ≥ ${kmoney(num(g.minSpend) ?? 0)}` : "Quà khi mua sản phẩm"), gift, trigger } };
    }
    case "product_discount": {
      const d = f.product_discount;
      const { rows, problem } = varRows(d.rows, d.mode, "discount_pct");
      if (problem) return no(problem);
      return {
        problem: null,
        version: { kind: "product_discount", label: clip(d.mode === "pct" ? `Giảm ${d.rows.map((r) => num(r.value)).find((n) => n) ?? ""}%` : "Giảm về giá mới"), item_id: id, variations: rows, ...dated(d.start, d.end), ...opt("per_buyer_limit", d.perBuyer) },
      };
    }
    case "price_flash": {
      const p = f.price_flash;
      if (p.what === "price") {
        const out: Record<string, unknown>[] = [];
        for (const r of p.rows) {
          const n = num(r.value);
          if (n === null) continue;
          if (p.mode === "pct" && (n < -50 || n > 100)) return no("Đổi giá trong khoảng −50% đến +100%.");
          if (p.mode === "final_price" && n <= 0) return no("Nhập giá bán lớn hơn 0.");
          out.push({ variation_id: r.variationId, [p.mode === "pct" ? "change_pct" : "final_price"]: n });
        }
        if (out.length === 0) return no("Nhập giá mới cho ít nhất một phân loại.");
        return { problem: null, version: { kind: "price", label: "Đổi giá niêm yết", item_id: id, variations: out } };
      }
      const { rows, problem } = varRows(p.rows, p.mode, "discount_pct");
      if (problem) return no(problem);
      const units = num(p.units);
      if (units === null || units <= 0) return no("Nhập số lượng suất flash sale.");
      return { problem: null, version: { kind: "flash_sale", label: "Flash sale", item_id: id, variations: rows, units, ...(p.slotStart ? { slot_start: p.slotStart } : {}), slot_hours: Math.max(1, Math.min(72, Math.round(num(p.slotHours) ?? 2))) } };
    }
    case "variation_set": {
      const out: Record<string, unknown>[] = [];
      for (const r of f.variation_set.rows) {
        if (!r.name.trim() && !r.price.trim()) continue;
        const price = num(r.price);
        if (!r.name.trim() || price === null || price <= 0) return no("Mỗi phân loại mới cần tên và giá.");
        out.push({ name: r.name.trim(), price, ...(r.sku.trim() ? { sku: r.sku.trim() } : {}), ...opt("pack_count", r.packCount), ...opt("stock", r.stock) });
      }
      if (out.length === 0) return no("Thêm ít nhất một phân loại mới.");
      return { problem: null, version: { kind: "variation_set", label: clip(`Thêm ${out.map((o) => String(o["name"])).join(", ")}`), item_id: id, new_variations: out } };
    }
    case "ads": {
      const a = f.ads;
      if (a.lever === "keywords") {
        const kws = a.keywords.filter((k) => k.keyword.trim());
        if (kws.length === 0) return no("Nhập ít nhất một từ khoá.");
        const out = [];
        for (const k of kws) {
          const bid = num(k.bid);
          if (bid === null || bid <= 0) return no("Nhập giá thầu cho từng từ khoá.");
          out.push({ keyword: k.keyword.trim(), bid, match: k.match });
        }
        return { problem: null, version: { kind: "ads", label: "Từ khoá và giá thầu", lever: "keywords", keywords: out } };
      }
      if (!a.campaignKey) return no("Chọn chiến dịch.");
      if (a.lever === "budget") {
        const n = num(a.dailyBudget);
        if (n === null || n <= 0) return no("Nhập ngân sách mỗi ngày.");
        return { problem: null, version: { kind: "ads", label: clip(`Ngân sách ${kmoney(n)}/ngày`), lever: "budget", campaign_key: a.campaignKey, daily_budget: n } };
      }
      if (a.lever === "roas") {
        const n = num(a.roasTarget);
        if (n === null || n <= 0) return no("Nhập ROAS mục tiêu.");
        return { problem: null, version: { kind: "ads", label: clip(`ROAS mục tiêu ${fmt(n, 1)}`), lever: "roas", campaign_key: a.campaignKey, roas_target: n } };
      }
      const item = a.itemId || id;
      return { problem: null, version: { kind: "ads", label: a.lever === "add_product" ? "Thêm sản phẩm vào chiến dịch" : "Gỡ sản phẩm khỏi chiến dịch", lever: a.lever, campaign_key: a.campaignKey, item_id: item } };
    }
    case "title": {
      const t = f.title.text.trim();
      if (!t) return no("Nhập hoặc chọn một tiêu đề.");
      if ([...t].length > MAX_TITLE) return no(`Tiêu đề tối đa ${MAX_TITLE} ký tự.`);
      return { problem: null, version: { kind: "title", label: "Tiêu đề mới", item_id: id, title: t, keywords: [...f.title.ticked] } };
    }
    case "cover_image": {
      const o = f.cover_image.overlay;
      if (!o) return no("Chọn một lớp chữ cho ảnh bìa.");
      return { problem: null, version: { kind: "cover_image", label: clip(o.badge_text || o.hook_text || o.pack_text || "Ảnh bìa"), item_id: id, overlay: o } };
    }
    case "description_first_line": {
      const t = f.description_first_line.text.trim();
      if (!t) return no("Nhập hoặc chọn dòng đầu của mô tả.");
      if (/[\r\n]/.test(t)) return no("Dòng đầu không xuống dòng.");
      if ([...t].length > MAX_FIRST_LINE) return no(`Dòng đầu tối đa ${MAX_FIRST_LINE} ký tự.`);
      return { problem: null, version: { kind: "description_first_line", label: "Dòng đầu mô tả", item_id: id, first_line: t } };
    }
    case "affiliate": {
      const a = f.affiliate;
      const pct = num(a.commission);
      if (pct === null || pct < 0 || pct > 50) return no("Hoa hồng từ 0% đến 50%.");
      const samples = Math.round(num(a.samples) ?? 0);
      if (samples < 0 || samples > 50) return no("Số mẫu gửi từ 0 đến 50.");
      return { problem: null, version: { kind: "affiliate", label: clip(`Hoa hồng ${fmt(pct, 1)}%`), item_id: id, commission_pct: pct, target_campaign: a.campaign.trim(), sample_qty: samples, ...opt("sample_ship_fee", a.shipFee) } };
    }
    case "price_display": {
      const p = f.price_display;
      if (p.what === "listing_hide") return { problem: null, version: { kind: "listing_hide", label: "Ẩn listing", item_id: id } };
      if (p.what === "listing_relist") return { problem: null, version: { kind: "listing_relist", label: "Đưa lại listing", item_id: id, ...opt("stock", p.stock) } };
      const v = ctx.variations[0];
      return { problem: null, version: { kind: "price_display", label: "Hiển thị giá mỗi đơn vị", item_id: id, ...(v && ctx.variations.length === 1 ? { variation_id: v.variation_id } : {}), ...(p.text.trim() ? { text: p.text.trim() } : {}) } };
    }
  }
}

// ── reading an outcome ───────────────────────────────────────────────────

export const refusalText = (o: Pick<BuilderOutcome, "refusal">): string => {
  const r = o.refusal;
  if (!r) return "Chưa tính được.";
  return typeof r === "string" ? r : (r.message ?? r.code ?? "Chưa tính được.");
};

export function bandText(b: Band | null | undefined, unit: "vnd" | "orders" = "vnd"): { readonly main: string; readonly range: string } {
  if (!b || b.p50 === null) return { main: DASH, range: "không đủ dữ liệu" };
  if (unit === "orders") {
    const o = (n: number | null) => (n === null ? DASH : `${n >= 0 ? "+" : "−"}${fmt(Math.abs(Math.round(n)))}`);
    return { main: `${o(b.p50)} đơn`, range: `${o(b.low)} – ${o(b.high)}` };
  }
  return { main: sv(b.p50), range: `${sv(b.low)} – ${sv(b.high)}` };
}

export function metricValue(unit: string, n: number | null): string {
  if (n === null) return DASH;
  if (unit === "vnd") return vnd(n);
  if (unit === "pct") return pp(n, 2);
  if (unit === "ratio") return fmt(n, 1);
  return fmt(Math.round(n));
}

export function breakEvenText(o: BuilderOutcome): string {
  const b = o.break_even;
  if (!b) return DASH;
  if (!b.applies) return b.reason ?? "Không có chi phí trực tiếp; đo sau khi chạy.";
  if (b.extra_orders === null) return b.reason ?? "Chưa đủ dữ liệu để tính mức hoà vốn.";
  const ctor = b.ctor_needed !== null ? `, tức CTOR ≥ ${pp(b.ctor_needed, 2)} (hôm nay ${pp(b.ctor_now, 2)})` : (b.ctor_reason ? `; ${b.ctor_reason}` : "");
  return `cần thêm ≥ ${fmt(Math.ceil(b.extra_orders))} đơn${ctor}, để lợi nhuận không giảm.`;
}

export const hasWarning = (o: Pick<BuilderOutcome, "warnings">, type: string): boolean => (o.warnings ?? []).some((w) => w.type === type);

export function floorWarningText(w: BuilderWarning): string {
  if (typeof w.message === "string" && w.message) return w.message;
  if (w.type === "floor") {
    const floor = typeof w.floor === "number" ? w.floor : null;
    const paid = typeof w.min_unit_price === "number" ? w.min_unit_price : null;
    return `${w.sku ?? "SKU"}: khách trả ${vnd(paid)} thấp hơn giá sàn ${vnd(floor)}${floor !== null && paid !== null ? ` (thiếu ${vnd(floor - paid)})` : ""}.`;
  }
  if (w.type === "spend_cap") return "Chi quảng cáo mỗi ngày vượt trần chi của Cài đặt › Mục tiêu.";
  if (w.type === "cost_unknown") return "Có sản phẩm chưa có giá vốn trong Thông số shop: lợi nhuận và biên chưa tính.";
  if (w.type === "floor_unknown") return "Chưa có giá vốn để tính giá sàn.";
  if (w.type === "profit_unknown") return "Chưa tính được lợi nhuận của phương án này.";
  if (w.type === "refused") return "Phương án này chưa tính được.";
  return "Xem chi tiết ở phương án.";
}

/** The breaches of one outcome, in the shape the warning dialog (and `choose`) uses. */
export function breachesOfOutcome(o: BuilderOutcome): readonly BuilderWarning[] {
  return (o.warnings ?? []).filter((w) => w.type === "floor" || w.type === "spend_cap");
}

export const BASIS_LABELS: readonly string[] = ["từ lịch sử sản phẩm", "của shop", "ước tính chung", "không đủ dữ liệu"];
