/**
 * Ảnh bìa banners (P100 S2-E; brief D Flow v4; design https://claude.ai/artifact/4SuySBPc5VbTQFU1SMK1wx).
 *
 * The E.7 banner spec the editor builds and the server stores: a template, a day mode and up to 3
 * (Ngày thường) or 4 (Mega Sale) banners. Each kind has one shape, and each shape fixed positions;
 * bottom-left is never offered (Shopee's voucher strip). Values are typed raw (money = integer đ,
 * % = number, text = text) and the display text is derived here exactly as
 * `backend/src/juli_backend/services/shopee_builder/banner.py` derives it
 * (`tests/fixtures/banner_cases.json` pins both). Rendering composites the banners over the real
 * cover in a canvas (PNG 1200 × 1200); nothing is generated and the photo is never altered.
 */

export type Shape = "ngang" | "goc" | "the";
export type Position = "top" | "top_left" | "top_right" | "middle_right" | "bottom_right";
export type TemplateId = "toi_gian" | "noi_bat" | "khung_vien";
export type DayMode = "ngay_thuong" | "mega_sale";
export type KindId = "mega" | "pct" | "genuine" | "freeship" | "combo" | "voucher" | "gift" | "addon" | "unit" | "quy_cach";
export type FieldType = "money" | "pct" | "int" | "text";
export type Value = number | string | null;

export interface Source {
  readonly card_id: string | null;
  readonly field: string;
}

export interface Banner {
  readonly shape: Shape;
  readonly kind: KindId;
  readonly values: Readonly<Record<string, Value>>;
  readonly sources: Readonly<Record<string, Source>>;
  readonly position: Position;
  readonly colour: string;
  readonly size: "S" | "M" | "L";
}

export interface Check {
  readonly code: string;
  readonly banner: number | null;
  readonly title: string;
  readonly fix: string;
}

export interface BannerSpec {
  readonly template: TemplateId;
  readonly day_mode: DayMode;
  readonly size_px: 1200;
  readonly banners: readonly Banner[];
  readonly checks: readonly Check[];
  readonly check_call_id: string | null;
}

export interface FieldDef {
  readonly key: string;
  readonly label: string;
  readonly type: FieldType;
  /** Shown in an empty field: where the value comes from, or that the seller types it. */
  readonly hint: string;
}

export interface KindDef {
  readonly id: KindId;
  readonly title: string;
  readonly shape: Shape;
  readonly megaOnly: boolean;
  /** Where its values come from (the design's "source" line). */
  readonly source: string;
  readonly fields: readonly FieldDef[];
}

const f = (key: string, label: string, type: FieldType, hint = ""): FieldDef => ({ key, label, type, hint });

/** The design's `catalog()`, in its order, plus Quy cách (brief D). */
export const KINDS: readonly KindDef[] = [
  { id: "mega", title: "Mega Sale", shape: "ngang", megaOnly: true, source: "Chiến dịch Shopee · bạn nhập tên, ngày", fields: [f("title", "Tên sale", "text", "11.11"), f("sub", "Dòng phụ", "text", "Siêu Sale"), f("dates", "Ngày", "text", "11/11 – 13/11")] },
  { id: "pct", title: "Giảm %", shape: "goc", megaOnly: false, source: "Từ thẻ Chương Trình Của Shop", fields: [f("pct", "% giảm", "pct", "từ thẻ")] },
  { id: "genuine", title: "Chính hãng", shape: "goc", megaOnly: false, source: "Từ tên sản phẩm", fields: [f("text", "Chữ", "text", "Chính hãng · Có VAT")] },
  { id: "freeship", title: "Freeship", shape: "goc", megaOnly: false, source: "Khi Juli đọc được chương trình Freeship", fields: [f("min", "Đơn từ (đ)", "money", "chưa đọc được")] },
  { id: "combo", title: "Combo", shape: "the", megaOnly: false, source: "Từ Tự tạo · Combo Khuyến Mãi", fields: [f("q1", "Mức 1 · mua", "int"), f("p1", "Mức 1 · giảm %", "pct"), f("q2", "Mức 2 · mua", "int"), f("p2", "Mức 2 · giảm %", "pct")] },
  { id: "voucher", title: "Voucher", shape: "the", megaOnly: false, source: "Từ thẻ voucher", fields: [f("value", "Giảm (đ)", "money"), f("min", "Đơn tối thiểu (đ)", "money")] },
  { id: "gift", title: "Quà tặng", shape: "the", megaOnly: false, source: "Từ thẻ Mua Để Nhận Quà", fields: [f("min", "Đơn từ (đ)", "money"), f("gift", "Tên quà", "text", "bạn nhập")] },
  { id: "addon", title: "Mua kèm", shape: "the", megaOnly: false, source: "Từ thẻ Mua Kèm Deal Sốc", fields: [f("item", "Sản phẩm kèm", "text", "bạn chọn"), f("pct", "Giảm %", "pct")] },
  { id: "unit", title: "Giá / đơn vị", shape: "the", megaOnly: false, source: "Từ giá bán · nhập số đơn vị trong gói", fields: [f("price", "Giá bán (đ)", "money"), f("qty", "Số đơn vị", "int", "bạn nhập"), f("unit", "Đơn vị", "text", "cuộn")] },
  { id: "quy_cach", title: "Quy cách", shape: "the", megaOnly: false, source: "Từ tên sản phẩm", fields: [f("text", "Quy cách", "text", "Hộp 100 cái")] },
];

export const kindOf = (id: string): KindDef | undefined => KINDS.find((k) => k.id === id);

export const SHAPES: Readonly<Record<Shape, { readonly name: string; readonly positions: readonly (readonly [Position, string])[] }>> = {
  ngang: { name: "Ngang", positions: [["top", "Dải trên"]] },
  goc: { name: "Góc", positions: [["top_left", "Trên trái"], ["top_right", "Trên phải"]] },
  the: { name: "Thẻ", positions: [["middle_right", "Giữa phải"], ["bottom_right", "Dưới phải"]] },
};

export const POSITION_LABEL: Readonly<Record<Position, string>> = {
  top: "Dải trên",
  top_left: "Trên trái",
  top_right: "Trên phải",
  middle_right: "Giữa phải",
  bottom_right: "Dưới phải",
};

export interface TemplateDef {
  readonly id: TemplateId;
  readonly name: string;
  readonly note: string;
  readonly radius: number;
  readonly fill: boolean;
  readonly frame: boolean;
}

export const TEMPLATES: readonly TemplateDef[] = [
  { id: "toi_gian", name: "Tối giản", note: "Nền trắng, viền mảnh, chữ màu shop", radius: 10, fill: false, frame: false },
  { id: "noi_bat", name: "Nổi bật", note: "Khối màu đặc, chữ trắng đậm", radius: 12, fill: true, frame: false },
  { id: "khung_vien", name: "Khung viền", note: "Viền màu quanh ảnh + khối màu", radius: 8, fill: true, frame: true },
];

export const templateOf = (id: string | null | undefined): TemplateDef => TEMPLATES.find((t) => t.id === id) ?? TEMPLATES[0];

export const DAY_MODES: readonly { readonly id: DayMode; readonly name: string; readonly note: string; readonly limit: number }[] = [
  { id: "ngay_thuong", name: "Ngày thường", note: "Ưu đãi thường xuyên: combo, voucher, quà, giá/đơn vị.", limit: 3 },
  { id: "mega_sale", name: "Mega Sale", note: "Ngày sale lớn (11.11, 12.12): thêm dải tên sale ở trên.", limit: 4 },
];

export const limitOf = (mode: DayMode | null | undefined): number => (mode === "mega_sale" ? 4 : 3);

/** The design's palette, used when the shop has no style profile yet. */
export const DEFAULT_PALETTE: readonly string[] = ["#2F7D4F", "#EE4D2D", "#121214", "#C98A00"];

export const HEAD_MAX = 22;
export const BANNER_MAX = 40;
export const TOTAL_MAX = 90;

// ── display text ──────────────────────────────────────────────────────────

const group = (n: number): string => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ".");

export function vnd(n: number): string {
  return `${group(Math.round(n))}đ`;
}

export function k(n: number): string {
  return n % 1000 === 0 ? `${group(n / 1000)}K` : vnd(n);
}

function num(v: Value | undefined): number | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "number") return v > 0 ? v : null;
  const digits = v.replace(/[^0-9]/g, "");
  return digits && Number(digits) > 0 ? Number(digits) : null;
}

function pctText(v: Value | undefined): string {
  const n = num(v);
  return n === null ? "" : String(n).replace(".", ",");
}

const txt = (v: Value | undefined): string => (typeof v === "string" ? v.trim() : "");

/** The banner's head and sub line (a missing value shows a bracketed placeholder, never a claim). */
export function bannerText(kind: KindId, values: Readonly<Record<string, Value>>): { readonly head: string; readonly sub: string } {
  const v = values;
  switch (kind) {
    case "mega": {
      const sub = txt(v.sub);
      return { head: (txt(v.title) || "Sale") + (sub ? ` · ${sub}` : ""), sub: txt(v.dates) };
    }
    case "pct": {
      const p = pctText(v.pct);
      return { head: p ? `−${p}%` : "−…%", sub: "" };
    }
    case "genuine":
      return { head: txt(v.text) || "Chính hãng", sub: "" };
    case "freeship": {
      const m = num(v.min);
      return { head: "Freeship", sub: m ? `Đơn từ ${k(m)}` : "" };
    }
    case "combo": {
      const [q1, p1, q2, p2] = [v.q1, v.p1, v.q2, v.p2].map(pctText);
      return { head: q1 && p1 ? `Mua ${q1} giảm ${p1}%` : "Combo", sub: q2 && p2 ? `Mua ${q2} giảm ${p2}%` : "" };
    }
    case "voucher": {
      const val = num(v.value);
      const m = num(v.min);
      return { head: val ? `Voucher giảm ${k(val)}` : "Voucher", sub: m ? `Đơn từ ${k(m)}` : "" };
    }
    case "gift": {
      const m = num(v.min);
      return { head: m ? `Mua từ ${k(m)}` : "Quà tặng", sub: `Tặng ${txt(v.gift) || "[tên quà]"}` };
    }
    case "addon": {
      const p = pctText(v.pct);
      return { head: `Mua kèm ${txt(v.item) || "[sản phẩm]"}`, sub: p ? `giảm ${p}%` : "" };
    }
    case "unit": {
      const price = num(v.price);
      const qty = num(v.qty);
      const unit = txt(v.unit) || "đơn vị";
      return price && qty ? { head: `Chỉ ${vnd(price / qty)}/${unit}`, sub: `${vnd(price)} · ${String(qty)} ${unit}` } : { head: `Giá / ${unit}`, sub: `Nhập số ${unit} trong gói` };
    }
    case "quy_cach":
      return { head: txt(v.text) || "[quy cách]", sub: "" };
  }
}

// ── rule checks (step 4) ──────────────────────────────────────────────────

const PLACEHOLDER = /\[|…|Nhập số/;

/** The design's step-4 checks, in its order (the server stores the same list). */
export function ruleChecks(spec: Pick<BannerSpec, "day_mode" | "banners">): Check[] {
  const out: Check[] = [];
  const byPos = new Map<Position, number[]>();
  spec.banners.forEach((b, i) => byPos.set(b.position, [...(byPos.get(b.position) ?? []), i]));
  const used = new Set(spec.banners.map((b) => b.position));
  for (const idx of byPos.values()) {
    if (idx.length < 2) continue;
    const mover = spec.banners[idx[1]];
    const free = SHAPES[mover.shape].positions.find(([p]) => !used.has(p));
    const names = idx.map((i) => kindOf(spec.banners[i].kind)?.title ?? "").join(" + ");
    out.push({
      code: "overlap",
      banner: idx[1],
      title: `Hai banner chồng nhau: ${names}`,
      fix: free ? `Chuyển ${kindOf(mover.kind)?.title ?? ""} sang ${free[1]}.` : "Bỏ bớt một banner cùng dạng.",
    });
  }
  let total = 0;
  spec.banners.forEach((b, i) => {
    const { head, sub } = bannerText(b.kind, b.values);
    total += head.length + sub.length;
    const name = kindOf(b.kind)?.title ?? b.kind;
    if (head.length > HEAD_MAX) out.push({ code: "text_long", banner: i, title: `${name}: dòng chính dài ${head.length} ký tự`, fix: `Giữ dưới ${HEAD_MAX} ký tự để đọc được trên điện thoại.` });
    if (PLACEHOLDER.test(head + sub)) out.push({ code: "empty_value", banner: i, title: `${name}: còn ô chưa có giá trị`, fix: "Điền giá trị ở bước 3 hoặc bỏ banner này." });
    if (head.length + 1 + sub.length > BANNER_MAX) out.push({ code: "overload", banner: i, title: `${name}: quá nhiều chữ`, fix: "Bỏ dòng phụ để ảnh thoáng hơn." });
  });
  if (total > TOTAL_MAX) out.push({ code: "overload", banner: null, title: `Tổng chữ trên ảnh: ${total} ký tự`, fix: `Ảnh bìa nhỏ trên điện thoại; nên giữ dưới ${TOTAL_MAX} ký tự.` });
  if (spec.day_mode === "mega_sale" && !spec.banners.some((b) => b.shape === "ngang")) out.push({ code: "missing_strip", banner: null, title: "Mega Sale chưa có dải tên sale", fix: "Thêm banner Mega Sale ở dải trên." });
  return out;
}

/** The one-click fix a check offers, when there is one: a new banner list. */
export function applyFix(spec: Pick<BannerSpec, "banners">, check: Check): Banner[] | null {
  if (check.banner === null) return null;
  const b = spec.banners[check.banner];
  if (!b) return null;
  if (check.code === "overlap") {
    const used = new Set(spec.banners.map((x) => x.position));
    const free = SHAPES[b.shape].positions.find(([p]) => !used.has(p));
    return free ? spec.banners.map((x, i) => (i === check.banner ? { ...x, position: free[0] } : x)) : null;
  }
  if (check.code === "overload") {
    const drop = b.kind === "mega" ? "dates" : b.kind === "combo" ? "q2" : null;
    if (!drop) return null;
    return spec.banners.map((x, i) => (i === check.banner ? { ...x, values: { ...x.values, [drop]: null } } : x));
  }
  return null;
}

// ── editing ───────────────────────────────────────────────────────────────

/** A typed value from what the seller typed (money/int: digits only; % keeps a decimal). */
export function parseValue(type: FieldType, raw: string): Value {
  const s = raw.trim();
  if (!s) return null;
  if (type === "text") return s.slice(0, 60);
  if (type === "pct") {
    const n = Number(s.replace(",", ".").replace(/[^0-9.]/g, ""));
    return Number.isFinite(n) && n > 0 ? Math.min(n, 100) : null;
  }
  const d = s.replace(/[^0-9]/g, "");
  return d ? Number(d) : null;
}

export function showValue(type: FieldType, v: Value | undefined): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number" && type === "pct") return String(v).replace(".", ",");
  return String(v);
}

export interface Prefill {
  readonly values: Readonly<Record<string, Value>>;
  readonly sources: Readonly<Record<string, Source>>;
}

/** A new banner of `kind` on the first free position of its shape, filled from what Juli read. */
export function newBanner(kind: KindDef, banners: readonly Banner[], palette: readonly string[], prefill?: Prefill): Banner {
  const used = new Set(banners.map((b) => b.position));
  const positions = SHAPES[kind.shape].positions;
  const free = positions.find(([p]) => !used.has(p)) ?? positions[0];
  const colour = (kind.shape === "the" ? palette[0] : palette[1] ?? palette[0]) ?? DEFAULT_PALETTE[0];
  return { shape: kind.shape, kind: kind.id, values: { ...(prefill?.values ?? {}) }, sources: { ...(prefill?.sources ?? {}) }, position: free[0], colour, size: "M" };
}

/** Switching the day mode keeps what still fits (and drops the strip off a Mega Sale). */
export function fitToMode(banners: readonly Banner[], mode: DayMode): Banner[] {
  return banners.filter((b) => mode === "mega_sale" || !kindOf(b.kind)?.megaOnly).slice(0, limitOf(mode));
}

export function specOf(template: TemplateId, mode: DayMode, banners: readonly Banner[]): BannerSpec {
  const base = { day_mode: mode, banners };
  return { template, day_mode: mode, size_px: 1200, banners: [...banners], checks: ruleChecks(base), check_call_id: null };
}

export function summary(banners: readonly Banner[]): string {
  return banners.map((b) => {
    const t = bannerText(b.kind, b.values);
    return t.head + (t.sub ? ` (${t.sub})` : "");
  }).join("; ");
}

// ── layout + render ───────────────────────────────────────────────────────

/** Where each position sits, in % of the cover (the design's `POS`), for a template's inset. */
export function placeOf(position: Position, frame: boolean): { top?: number; bottom?: number; left?: number; right?: number; w: number; align: "center" | "left" } {
  const inset = frame ? 7 : 4;
  switch (position) {
    case "top":
      return { top: 0, left: 0, w: 100, align: "center" };
    case "top_left":
      return { top: inset, left: inset, w: 34, align: "center" };
    case "top_right":
      return { top: inset, right: inset, w: 34, align: "center" };
    case "middle_right":
      return { top: 40, right: inset, w: 52, align: "left" };
    case "bottom_right":
      return { bottom: inset, right: inset, w: 52, align: "left" };
  }
}

const FONT = '"Be Vietnam Pro", system-ui, sans-serif';

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/** Draw the cover and its banners on a 1200 px canvas (the design's `download()`). */
export function drawCover(ctx: CanvasRenderingContext2D, image: CanvasImageSource | null, spec: Pick<BannerSpec, "template" | "banners">, frameColour: string): void {
  const S = 1200;
  ctx.fillStyle = "#ececf0";
  ctx.fillRect(0, 0, S, S);
  if (image) {
    const iw = (image as HTMLImageElement).naturalWidth || (image as HTMLImageElement).width || S;
    const ih = (image as HTMLImageElement).naturalHeight || (image as HTMLImageElement).height || S;
    const r = Math.max(S / iw, S / ih);
    ctx.drawImage(image, (S - iw * r) / 2, (S - ih * r) / 2, iw * r, ih * r);
  }
  const tpl = templateOf(spec.template);
  if (tpl.frame) {
    ctx.lineWidth = 36;
    ctx.strokeStyle = frameColour;
    ctx.strokeRect(18, 18, S - 36, S - 36);
  }
  for (const b of spec.banners) {
    const t = bannerText(b.kind, b.values);
    const p = placeOf(b.position, tpl.frame);
    const strip = b.shape === "ngang";
    const headPx = strip ? 64 : 44;
    const subPx = 30;
    const pad = 24;
    ctx.font = `700 ${headPx}px ${FONT}`;
    const hw = ctx.measureText(t.head).width;
    ctx.font = `500 ${subPx}px ${FONT}`;
    const sw = t.sub ? ctx.measureText(t.sub).width : 0;
    const w = p.w === 100 ? S : Math.min((S * p.w) / 100, Math.max(hw, sw) + pad * 2);
    const h = headPx * 1.25 + (t.sub ? subPx * 1.35 : 0) + pad * 2;
    const x = p.left !== undefined ? (S * p.left) / 100 : S - (S * (p.right ?? 0)) / 100 - w;
    const y = p.top !== undefined ? (S * p.top) / 100 : S - (S * (p.bottom ?? 0)) / 100 - h;
    const fill = tpl.fill || strip;
    ctx.fillStyle = fill ? b.colour : "#ffffff";
    roundRect(ctx, x, y, w, h, p.w === 100 ? 0 : tpl.radius * 2);
    ctx.fill();
    if (!fill) {
      ctx.lineWidth = 4;
      ctx.strokeStyle = b.colour;
      ctx.stroke();
    }
    ctx.fillStyle = fill ? "#ffffff" : b.colour;
    ctx.textBaseline = "top";
    ctx.textAlign = p.align === "center" ? "center" : "left";
    const tx = p.align === "center" ? x + w / 2 : x + pad;
    ctx.font = `700 ${headPx}px ${FONT}`;
    ctx.fillText(t.head, tx, y + pad, w - pad * 2);
    if (t.sub) {
      ctx.font = `500 ${subPx}px ${FONT}`;
      ctx.fillText(t.sub, tx, y + pad + headPx * 1.25, w - pad * 2);
    }
  }
}
