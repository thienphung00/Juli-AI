import { DASH, fmt, vnd, type Tone } from "../shopee-analytics/format";
import { parseServerIso } from "../vn-format";
import { expectedRows, sureRows, vnWhen } from "./model";
import { aovText, ordersText, perOrderNoun, sm, srange, um, unitsOf } from "./units";
import type { Breach, Card, CardDetail, CardSummary, CardVersion, N, ProductMeasuring, VersionBrief } from "./types";

/**
 * Versions inside a card (P91 D-2) and everything the P91 screens say about them: the side-by-side
 * table of `CardVersions.dc.html`, the breach warning (floor and spend cap never block: they need a
 * yes that is recorded), the product queue ("#1 · Đang ở Quyết định"), the title limit and the
 * "Sản phẩm đang đo" countdown. Field names are the backend's (`versions.py`, `service._summary`).
 */

export const MAX_TITLE_CHARS = 100;
export const MIN_MEASURE_DAYS = 3;

const num = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

/** Money to the nearest nghìn, as the artboards print it. */
export const roundK = (n: number): number => Math.round(n / 1000) * 1000;
const MINUS = "−";
/** "+60.000đ" / "−1.000đ", rounded to nghìn. */
export function svk(n: N | undefined): string {
  if (!num(n)) return DASH;
  const r = roundK(n);
  return `${r >= 0 ? "+" : MINUS}${fmt(Math.abs(r))}đ`;
}
/** "+60.000đ – +210.000đ" (one value when both ends round to the same). */
export function rangeK(lo: N | undefined, hi: N | undefined): string {
  if (!num(lo) || !num(hi)) return DASH;
  const a = Math.min(lo, hi);
  const b = Math.max(lo, hi);
  return roundK(a) === roundK(b) ? svk(a) : `${svk(a)} – ${svk(b)}`;
}
/** Tone of a profit range: green when it cannot lose, red when it cannot gain. */
export function rangeTone(lo: N | undefined, hi: N | undefined): Tone | "plain" {
  if (!num(lo) || !num(hi)) return "plain";
  const a = Math.min(lo, hi);
  const b = Math.max(lo, hi);
  return a >= 0 ? "up" : b <= 0 ? "down" : "plain";
}

// ── Versions of a card ──────────────────────────────────────────────────────

/** The card's versions; a card made before P91 has just its own evaluation as version 1. */
export function versionsOf(card: Card): readonly CardVersion[] {
  if (card.versions && card.versions.length > 0) return card.versions;
  return [
    {
      version: 1,
      code: card.code ? `${card.code}-V1` : null,
      label: "Mặc định của Juli",
      status: card.floor.ok ? "ok" : "floor_breach",
      default: true,
      ranked: true,
      refusal: null,
      inputs: card.inputs,
      reason: card.reason,
      change: card.change,
      whatif: card.whatif,
      certain: card.certain,
      five_numbers: card.five_numbers,
      floor: card.floor,
      spend: card.spend,
      predicted: card.predicted,
      measurement_plan: card.measurement_plan,
      execution_sheet: card.execution_sheet,
      notes: card.notes,
    },
  ];
}

export const isRefused = (v: Pick<CardVersion, "status"> | Pick<VersionBrief, "status">): boolean => v.status === "refused";

/** The card as it reads when version `v` is the one in view (its evaluation over the card). */
export function cardOfVersion(card: Card, v: CardVersion): Card {
  if (isRefused(v) || !v.five_numbers) return card;
  return {
    ...card,
    version: v.version,
    reason: v.reason ?? card.reason,
    change: v.change ?? card.change,
    inputs: v.inputs,
    whatif: v.whatif ?? card.whatif,
    certain: v.certain ?? card.certain,
    five_numbers: v.five_numbers,
    floor: v.floor ?? card.floor,
    spend: v.spend === undefined ? card.spend : v.spend,
    predicted: v.predicted ?? card.predicted,
    measurement_plan: v.measurement_plan ?? card.measurement_plan,
    execution_sheet: v.execution_sheet ?? card.execution_sheet,
    notes: v.notes ?? card.notes,
  };
}

export const versionName = (v: Pick<CardVersion, "version">): string => `V${v.version}`;

/** The code of version `n` of a card: the backend's, else `<card code>-Vn`. */
export function versionCode(card: Pick<Card, "code">, v: Pick<CardVersion, "version" | "code">): string {
  return v.code ?? (card.code ? `${card.code}-V${v.version}` : versionName(v));
}

// ── Breaches (never block, always acknowledged) ─────────────────────────────

/** Floor and spend-cap breaches of one evaluation (`versions.breaches_of`). */
export function breachesOf(card: Pick<Card, "floor" | "spend">): Breach[] {
  const out: Breach[] = (card.floor?.breaches ?? []).map((b) => ({ type: "floor", ...b }));
  const s = card.spend;
  if (s?.over_cap === true) out.push({ type: "spend_cap", spend_after: s.shop_chi_per_day_after, cap: s.cap });
  return out;
}

export const hasFloor = (bs: readonly Breach[]): boolean => bs.some((b) => b.type === "floor");
export const hasSpend = (bs: readonly Breach[]): boolean => bs.some((b) => b.type === "spend_cap");

/** "chạm giá sàn" | "vượt trần chi" | "chạm giá sàn và vượt trần chi". */
export function breachNoun(bs: readonly Breach[]): string {
  return hasFloor(bs) && hasSpend(bs) ? "chạm giá sàn và vượt trần chi" : hasSpend(bs) ? "vượt trần chi" : "chạm giá sàn";
}

/** "vượt giá sàn" | "vượt trần chi" | "vượt giá sàn và trần chi". */
export function breachVerb(bs: readonly Breach[]): string {
  return hasFloor(bs) && hasSpend(bs) ? "vượt giá sàn và trần chi" : hasSpend(bs) ? "vượt trần chi" : "vượt giá sàn";
}

/** One sentence per breach for the warning dialog: each shortfall in đ and the amount over the cap. */
export function breachWarnLines(bs: readonly Breach[]): string[] {
  return bs.map((b) => {
    if (b.type === "floor") {
      const floor = num(b.floor) ? b.floor : null;
      const paid = num(b.min_unit_price) ? b.min_unit_price : null;
      const short = floor !== null && paid !== null ? `, thiếu ${vnd(floor - paid)}` : "";
      const absolute = b.kind === "absolute";
      return `Giá sàn: ${b.sku ?? "SKU"}, khách trả ${vnd(paid)} thấp hơn ${absolute ? "giá sàn tuyệt đối" : "sàn vận hành"} ${vnd(floor)}${short} (${absolute ? "đang lỗ" : "chưa lỗ"}).`;
    }
    const after = num(b.spend_after) ? b.spend_after : num(b.spend_per_day_after) ? b.spend_per_day_after : null;
    const cap = num(b.cap) ? b.cap : null;
    const over = after !== null && cap !== null ? `, vượt ${vnd(after - cap)} mỗi ngày` : "";
    return `Trần chi: chi marketing ${vnd(after)} / ngày vượt trần ${vnd(cap)}${over}.`;
  });
}

/** "04/11/2026 10:15" in Vietnam time. */
export function vnWhenFull(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const t = parseServerIso(iso);
  if (!Number.isFinite(t)) return DASH;
  const parts = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "Asia/Ho_Chi_Minh" }).formatToParts(new Date(t));
  const get = (type: string) => parts.find((x) => x.type === type)?.value ?? "";
  return `${get("day")}/${get("month")}/${get("year")} ${get("hour")}:${get("minute")}`;
}

/** "Đã xác nhận vượt giá sàn · 04/11/2026 10:15". */
export function ackText(bs: readonly Breach[], at: string | null | undefined): string {
  return `Đã xác nhận ${breachVerb(bs)} · ${vnWhenFull(at)}`;
}

/** The acknowledgement a card carries (manual cards store it on the card; an approval on the detail), if any. */
export function ackOf(detail: Pick<CardDetail, "acknowledged_breaches" | "card" | "journey">): { readonly breaches: readonly Breach[]; readonly at: string | null } | null {
  const direct = detail.acknowledged_breaches ?? detail.card.acknowledged_breaches ?? null;
  if (direct?.breaches && direct.breaches.length > 0) return { breaches: direct.breaches, at: direct.at ?? null };
  const ev = [...detail.journey].reverse().find((e) => e.event === "accepted" && e.payload && Array.isArray((e.payload as { acknowledged_breaches?: unknown }).acknowledged_breaches));
  if (ev) {
    const p = ev.payload as { acknowledged_breaches?: { at?: string; breaches?: Breach[] } };
    const a = p.acknowledged_breaches;
    if (a?.breaches?.length) return { breaches: a.breaches, at: a.at ?? ev.at };
  }
  return null;
}

// ── Queue and measuring ─────────────────────────────────────────────────────

export function queueLabel(queue: number | null | undefined): string {
  if (!num(queue)) return DASH;
  return queue === 1 ? "#1 · Đang ở Quyết định" : `#${queue} · Xếp hàng`;
}

export const CLOSED_STATUSES: readonly string[] = ["rejected", "expired", "executed", "superseded", "withdrawn"];
export const OPEN_STATUSES: readonly string[] = ["draft", "sent", "changes_requested", "approved"];

export const isOpen = (c: Pick<CardSummary, "status">): boolean => OPEN_STATUSES.includes(c.status);

/** The "Sản phẩm đang đo: còn N ngày" count: days from today to the last day of the measurement window, both included. */
export function measuringDaysLeft(m: ProductMeasuring | null | undefined, now: Date): number {
  if (!m?.until) return 0;
  const until = Date.parse(`${m.until.slice(0, 10)}T00:00:00+07:00`);
  if (!Number.isFinite(until)) return 0;
  const today = new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", day: "2-digit", timeZone: "Asia/Ho_Chi_Minh" }).format(now);
  const diff = Math.round((until - Date.parse(`${today}T00:00:00+07:00`)) / 86_400_000);
  return diff >= 0 ? diff + 1 : 0;
}

/** The window under "Sản phẩm đang đo". */
export function measuringNote(m: ProductMeasuring | null | undefined): string {
  const cs = (m?.change_set ?? null) as { readonly window_days?: number; readonly days?: number } | null;
  const days = cs?.window_days ?? cs?.days;
  return num(days) ? `Cửa sổ ${fmt(days, 0)} ngày` : "";
}

/** "Δ lợi nhuận V1 +60.000đ – +210.000đ/tháng" from the list's version brief or the card's first version. */
export function firstVersionRange(card: Pick<CardSummary, "predicted_summary">): string {
  const q = card.predicted_summary.dprofit_month;
  const days = Math.max(1, card.predicted_summary.effect_days || 1);
  const per = (n: N) => (num(n) ? n / days : null);
  return `${srange(per(q.p10), per(q.p90))}/ngày (trong ${fmt(days, 0)} ngày: ${rangeK(q.p10, q.p90)})`;
}

// ── Title (D-4) ─────────────────────────────────────────────────────────────

export const isTitleKind = (card: Pick<Card, "change_kind">): boolean => card.change_kind === "title";

/** One live value at a time (P94): a second option of these starts the next group, so the card stays a single choice. */
export function oneLiveValue(kind: string): boolean {
  return (
    kind === "title" ||
    kind === "price" ||
    kind === "cover" ||
    kind === "description" ||
    kind === "main_image" ||
    kind === "discount" ||
    kind.includes("budget") ||
    kind.includes("roas")
  );
}
export const titleOf = (inputs: Readonly<Record<string, unknown>>): string => (typeof inputs["title"] === "string" ? (inputs["title"] as string) : "");

export interface TitleCount {
  readonly n: number;
  readonly over: boolean;
  readonly note: string;
  readonly tone: "up" | "warn" | "down";
}

export function titleCount(text: string): TitleCount {
  const n = text.length;
  const over = n > MAX_TITLE_CHARS;
  return {
    n,
    over,
    tone: over ? "down" : n > 90 ? "warn" : "up",
    note: over ? `Quá ${n - MAX_TITLE_CHARS} ký tự. Phần vượt không được lưu và Duyệt bị khoá.` : `Còn ${MAX_TITLE_CHARS - n} ký tự.`,
  };
}

// ── The side-by-side table ──────────────────────────────────────────────────

export interface TableCell {
  readonly v: string;
  /** "▲ +0,6 điểm" and so on; empty when there is no change to name. */
  readonly d: string;
  readonly tone: Tone | "plain" | "muted";
  readonly bad: boolean;
}

export interface TableRow {
  readonly key: string;
  readonly label: string;
  readonly sub: string;
  /** The "Hôm nay" cell; `null` = not known (printed "—"). */
  readonly today: string | null;
  readonly cells: readonly TableCell[];
}

function rowFrom(key: string, label: string, sub: string, today: string | null, cells: readonly TableCell[]): TableRow {
  return { key, label, sub, today, cells };
}

/** The versions as columns next to "Hôm nay": rows ①…⑤, Chi phí, Δ chắc chắn, Δ dự kiến, giá sàn and trần chi (or the title limit). */
export function versionTable(card: Card, versions: readonly CardVersion[]): TableRow[] {
  const per = versions.map((v) => {
    if (isRefused(v) || !v.five_numbers) return null;
    const c = cardOfVersion(card, v);
    return { v, c, sure: sureRows(c), exp: expectedRows(c) };
  });
  const first = per.find((p) => p !== null) ?? null;
  const title = isTitleKind(card);
  const cellOf = (pick: (p: NonNullable<(typeof per)[number]>) => TableCell): TableCell[] => per.map((p) => (p ? pick(p) : { v: "Không tính được", d: "", tone: "muted" as const, bad: false }));
  const fromRow = (rows: "sure" | "exp", i: number, delta: "dp" | "dv"): ((p: NonNullable<(typeof per)[number]>) => TableCell) => (p) => {
    const r = p[rows][i]!;
    const d = delta === "dp" ? r.dp : r.dv;
    const arrow = r.tone === "up" ? "▲ " : r.tone === "down" ? "▼ " : "";
    return { v: r.after, d: d && d !== DASH ? `${arrow}${d}` : "", tone: r.tone, bad: false };
  };
  const rows: TableRow[] = [
    rowFrom("disc", "① Giảm giá", "% GMV niêm yết", first?.sure[0]?.before ?? null, cellOf(fromRow("sure", 0, "dp"))),
    rowFrom("eff", "② Hiệu quả chi", "ΔGMV ÷ Δchi", null, cellOf((p) => ({ v: p.exp[1]!.after, d: "", tone: "plain", bad: false }))),
    rowFrom("bien", "③ Biên lợi nhuận", "trên tiền khách trả", first?.sure[2]?.before ?? null, cellOf(fromRow("exp", 2, "dp"))),
    rowFrom(
      "orders",
      "④ Số đơn",
      "theo mô hình",
      first?.exp[3]?.before ?? null,
      cellOf((p) => {
        const o = ordersText(p.c);
        if (!o) return fromRow("exp", 3, "dv")(p);
        return { v: o.perDay, d: `${fmt(unitsOf(p.c).days, 0)} ngày: ${o.period}${o.changes ? "" : " · số đơn giữ nguyên (đòn bẩy giỏ hàng)"}`, tone: "plain", bad: false };
      }),
    ),
    rowFrom(
      "aov",
      "⑤ AOV",
      "GMV ÷ số đơn",
      first?.exp[4]?.before ?? null,
      cellOf((p) => {
        const a = aovText(p.c);
        if (!a) return fromRow("exp", 4, "dv")(p);
        return { v: a.range, d: a.certain, tone: "plain", bad: false };
      }),
    ),
    rowFrom(
      "chi",
      "Chi phí",
      "chi marketing mỗi ngày · mỗi đơn · cả đợt",
      null,
      cellOf((p) => {
        const u = unitsOf(p.c);
        const d = u.perDay.dchi;
        if (!num(d)) return { v: DASH, d: "", tone: "plain", bad: false };
        const tone = d > 0 ? "down" : d < 0 ? "up" : "plain";
        if (Math.abs(d) < 10) return { v: "Không đổi", d: "", tone, bad: false };
        const unit = u.perOrder && num(u.perOrder.cost) && u.perOrder.cost !== 0 ? `${um(u.perOrder.cost)}/${perOrderNoun(u)} · ` : "";
        return { v: `${sm(d)}/ngày`, d: `${unit}${fmt(u.days, 0)} ngày: ${sm(u.period.dchi)}`, tone, bad: false };
      }),
    ),
    rowFrom(
      "sure",
      "Δ lợi nhuận · chắc chắn",
      "nếu khách mua như 30 ngày qua",
      null,
      cellOf((p) => {
        const u = unitsOf(p.c);
        const d = u.perDay.certain;
        if (title || (card.family === "listing" && (!num(d) || d === 0))) return { v: "Không tốn chi phí", d: "", tone: "muted", bad: false };
        const perOrder = u.perOrder && num(u.perOrder.certain) ? `${sm(u.perOrder.certain)}/${perOrderNoun(u)} · ` : "";
        return { v: num(d) ? `${sm(d)}/ngày` : DASH, d: `${perOrder}${fmt(u.days, 0)} ngày: ${sm(u.period.certain)}`, tone: num(d) ? (d >= 0 ? "up" : "down") : "plain", bad: false };
      }),
    ),
    rowFrom(
      "exp",
      "Δ lợi nhuận",
      "khoảng, theo mô hình tăng đơn",
      null,
      cellOf((p) => {
        const u = unitsOf(p.c);
        const perOrder = u.perOrder && num(u.perOrder.p50) ? `giữa khoảng ${sm(u.perOrder.p50)}/${perOrderNoun(u)} · ` : "";
        return { v: `${srange(u.perDay.p10, u.perDay.p90)}/ngày`, d: `${perOrder}${fmt(u.days, 0)} ngày: ${srange(u.period.p10, u.period.p90)}`, tone: rangeTone(u.period.p10, u.period.p90), bad: false };
      }),
    ),
    rowFrom(
      "floor",
      "Giá sàn",
      title ? "" : "giỏ nhỏ nhất đủ điều kiện",
      null,
      cellOf((p) => {
        if (title) return { v: "Không áp dụng: không đổi giá", d: "", tone: "plain", bad: false };
        const f = p.c.floor;
        if (f.ok) return { v: "✓ Trên giá sàn vận hành", d: "", tone: "plain", bad: false };
        const b = f.breaches[0];
        const text = b ? `✕ Khách trả ${vnd(b.min_unit_price)} < sàn ${vnd(b.floor)}${num(b.floor) && num(b.min_unit_price) ? ` (thiếu ${vnd(b.floor - b.min_unit_price)})` : ""}` : "✕ Chạm giá sàn";
        return { v: f.breaches.length > 1 ? `${text} · +${f.breaches.length - 1} SKU` : text, d: "", tone: "down", bad: true };
      }),
    ),
  ];
  if (title) {
    rows.push(
      rowFrom(
        "limit",
        "Giới hạn 100 ký tự",
        "mọi tiêu đề",
        null,
        cellOf((p) => {
          const n = titleOf(p.v.inputs).length;
          const over = n > MAX_TITLE_CHARS;
          return { v: over ? `✕ ${n}/100 ký tự: quá giới hạn` : `✓ ${n}/100 ký tự · không tốn chi phí`, d: "", tone: over ? "down" : "plain", bad: over };
        }),
      ),
    );
  } else {
    rows.push(
      rowFrom(
        "cap",
        "Trần chi",
        "chi marketing / ngày",
        null,
        cellOf((p) => {
          const s = p.c.spend;
          if (!s || !num(s.shop_chi_per_day_after)) return { v: DASH, d: "", tone: "muted", bad: false };
          const over = s.over_cap === true;
          const cap = num(s.cap) ? (over ? `vượt trần ${vnd(s.cap)}/ngày` : `trong trần ${vnd(s.cap)}/ngày`) : "chưa đặt trần";
          return { v: `${over ? "✕" : "✓"} Chi marketing ${vnd(s.shop_chi_per_day_after)}/ngày · ${cap}`, d: "", tone: over ? "down" : "plain", bad: over };
        }),
      ),
    );
  }
  if (card.family === "voucher" && per.some((p) => p?.c.certain.voucher_detail)) rows.push(...voucherRows(per, versions));
  return rows;
}

type Per = { readonly v: CardVersion; readonly c: Card } | null;

/** Usage vs limit, per-buyer limit, max discount and the one-line reason two versions look alike. */
function voucherRows(per: readonly (Per | { readonly v: CardVersion; readonly c: Card; readonly sure: unknown; readonly exp: unknown })[], versions: readonly CardVersion[]): TableRow[] {
  const cell = (pick: (d: NonNullable<Card["certain"]["voucher_detail"]>, p: NonNullable<Per>) => TableCell): TableCell[] =>
    per.map((p) => {
      const d = p?.c.certain.voucher_detail;
      return p && d ? pick(d, p) : { v: DASH, d: "", tone: "muted" as const, bad: false };
    });
  return [
    rowFrom(
      "usage",
      "Số lượt dùng",
      "dùng / giới hạn",
      null,
      cellOf2(cell, (d) => {
        const u = d.usage;
        const used = num(u.used) ? fmt(u.used, Number.isInteger(u.used) || u.used >= 10 ? 0 : 1) : DASH;
        const limit = num(u.limit) ? fmt(u.limit, 0) : "không giới hạn";
        return { v: `Dùng ${used} / ${limit} lượt`, d: num(u.limit) ? (u.capped ? "chạm giới hạn" : "chưa chạm giới hạn") : "", tone: u.capped ? "down" : "plain", bad: false };
      }),
    ),
    rowFrom(
      "peruser",
      "Giới hạn mỗi người mua",
      "chưa tính vào kết quả",
      null,
      cellOf2(cell, (d) => ({ v: num(d.per_user.limit) ? `${fmt(d.per_user.limit, 0)} lượt/người` : "Không đặt", d: num(d.per_user.limit) ? "chưa tính vào kết quả: đơn hàng không cho biết người mua" : "", tone: "muted", bad: false })),
    ),
    rowFrom(
      "maxd",
      "Mức giảm tối đa",
      "chỉ voucher giảm theo %",
      null,
      cellOf2(cell, (d) => {
        const m = d.max_discount;
        if (!m.applies) return { v: "Không đặt", d: "", tone: "muted", bad: false };
        if (!m.pct_voucher) return { v: um(m.value), d: "chỉ có tác dụng với voucher %", tone: "muted", bad: false };
        const binds = m.binding_orders > 0;
        return { v: um(m.value), d: binds ? `chạm trần ở ${fmt(m.binding_orders, 0)}/${fmt(m.qualifying_orders, 0)} đơn đủ điều kiện` : "chưa đơn nào chạm trần", tone: binds ? "down" : "plain", bad: false };
      }),
    ),
    rowFrom(
      "same",
      "Vì sao giống V1",
      "đầu vào khác nhưng kết quả không đổi",
      null,
      versions.map((v) => ({ v: v.same_as_default_notes && v.same_as_default_notes.length > 0 ? v.same_as_default_notes.join(" ") : DASH, d: "", tone: "muted" as const, bad: false })),
    ),
  ];
}

function cellOf2(cell: (pick: (d: NonNullable<Card["certain"]["voucher_detail"]>, p: NonNullable<Per>) => TableCell) => TableCell[], f: (d: NonNullable<Card["certain"]["voucher_detail"]>) => TableCell): TableCell[] {
  return cell((d) => f(d));
}

/** Column tag of a version: the engine's pick, a breach, a version that could not be priced. */
export function versionTag(v: CardVersion, index: number): { readonly text: string; readonly tone: "pink" | "down" | "flat" } {
  if (isRefused(v)) return { text: "Không tính được", tone: "down" };
  if (index === 0) return { text: "Juli đề xuất", tone: "pink" };
  if (v.status === "floor_breach") return { text: "Chạm giá sàn", tone: "down" };
  if (v.status === "spend_breach") return { text: "Vượt trần chi", tone: "down" };
  return { text: "Phiên bản", tone: "flat" };
}

/** Flag on a version row of the product's list: "Chạm giá sàn" / "Vượt trần chi" (a refused one has none to price). */
export function versionFlag(v: Pick<VersionBrief, "status">): string {
  return v.status === "floor_breach" ? "Chạm giá sàn" : v.status === "spend_breach" ? "Vượt trần chi" : v.status === "refused" ? "Không tính được" : "";
}

export { vnWhen };

/** Groups of the product's Đề xuất tab, in the artboard's order, with its names (`SanPhamDeXuat.dc.html` FAMILIES). */
export const PRODUCT_GROUPS: readonly (readonly [string, string])[] = [
  ["listing", "Tên, từ khoá, ảnh bìa"],
  ["ads", "Dịch vụ hiển thị"],
  ["promotion", "Khuyến mãi, giá"],
  ["voucher", "Voucher"],
  ["combo", "Combo"],
  ["affiliate", "Tiếp thị liên kết"],
  ["sale", "Flash Sale, chương trình"],
];
