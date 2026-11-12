import { parseServerIso } from "../vn-format";
import { DASH, chipFromChange, chipPt, fmt, pp, sv, vnd, type Chip, type Tone } from "../shopee-analytics/format";
import { FIVE_LABELS } from "../shopee-analytics/model";
import type { RankingLink } from "../shopee-analytics/links";
import type { Card, CardStatus, CardSummary, Family, FloorBreach, JourneyEvent, MoneyAt, N, SliderRow } from "./types";

/** Derivations the Shopee Quyết định screens share: sections, tabs, the two layers of numbers, floors, read-back. */

// ── Sections and tabs ───────────────────────────────────────────────────────

/** Section order of the list (ranking order inside each section is the API's). */
export const FAMILY_ORDER: readonly Family[] = ["listing", "ads", "promotion", "voucher", "sale", "combo", "affiliate", "mega_sale"];

export const FAMILY_TITLE: Readonly<Record<Family, string>> = {
  listing: "Tên, từ khoá, ảnh bìa",
  ads: "Dịch vụ hiển thị",
  promotion: "Khuyến mãi",
  voucher: "Voucher",
  sale: "Sale",
  combo: "Combo",
  affiliate: "Tiếp thị liên kết",
  mega_sale: "Mega sale",
};

export type DecisionTab = "de-xuat" | "dang-thuc-hien" | "do-luong";

export const TABS: readonly (readonly [DecisionTab, string])[] = [
  ["de-xuat", "Đề xuất"],
  ["dang-thuc-hien", "Đang thực hiện"],
  ["do-luong", "Đo lường"],
];

export function tabOfParam(raw: string | null | undefined): DecisionTab {
  return raw === "dang-thuc-hien" || raw === "do-luong" ? raw : "de-xuat";
}

/** Which tab lists a card; `null` = closed (không còn trong danh sách). */
export function tabOfCard(card: Pick<CardSummary, "status" | "verification">): DecisionTab | null {
  switch (card.status) {
    case "draft":
    case "sent":
    case "changes_requested":
      return "de-xuat";
    case "approved":
      return "dang-thuc-hien";
    case "executed": {
      const v = card.verification?.state;
      return v === "pending" || v === "mismatch" || v === "not_seen" ? "dang-thuc-hien" : "do-luong";
    }
    default:
      return null;
  }
}

export const STATUS_LABEL: Readonly<Record<string, string>> = {
  draft: "Nháp (chưa gửi shop)",
  sent: "Chờ duyệt",
  changes_requested: "Đã yêu cầu chỉnh",
  approved: "Đã duyệt · chờ làm",
  executed: "Đã làm",
  rejected: "Đã từ chối",
  expired: "Hết hạn",
  withdrawn: "Đã rút lại",
  superseded: "Đã thay bằng thẻ mới",
};

export function statusLabel(status: CardStatus): string {
  return STATUS_LABEL[status] ?? status;
}

export interface FamilySection {
  readonly family: Family;
  readonly title: string;
  readonly cards: readonly CardSummary[];
}

/** Cards of one tab, grouped by family in the fixed order; empty families are left out. */
export function sectionsFor(cards: readonly CardSummary[], tab: DecisionTab): FamilySection[] {
  const inTab = cards.filter((c) => tabOfCard(c) === tab);
  return FAMILY_ORDER.map((family) => ({ family, title: FAMILY_TITLE[family], cards: inTab.filter((c) => c.family === family) })).filter((s) => s.cards.length > 0);
}

export function tabCounts(cards: readonly CardSummary[]): Readonly<Record<DecisionTab, number>> {
  const out: Record<DecisionTab, number> = { "de-xuat": 0, "dang-thuc-hien": 0, "do-luong": 0 };
  for (const c of cards) {
    const t = tabOfCard(c);
    if (t) out[t] += 1;
  }
  return out;
}

/** "đáng thử": the slot ranking contract 11 keeps for a card outside the top score. */
export function isWorthTrying(card: Pick<CardSummary, "worth_trying" | "rank">): boolean {
  return card.worth_trying === true || card.rank?.explore === true;
}

// ── Link to the analytics ranking row ───────────────────────────────────────

const KPI_KEYS = new Set(["gmv", "views", "ctr", "ctor", "aov", "bien", "disc", "orders"]);
const KPI_OF_METRIC: Readonly<Record<string, string>> = { ads_gmv: "gmv", roas: "gmv", lien_ket: "gmv", sale: "orders", none: "gmv" };
const SRC_OF_FAMILY: Readonly<Record<Family, string>> = {
  listing: "all",
  ads: "ads",
  promotion: "promo",
  voucher: "voucher",
  sale: "promo",
  combo: "combo",
  affiliate: "lien_ket",
  mega_sale: "all",
};

/** The Xếp hạng row a card's "Xem phân tích ›" opens (VERIFY.md link table: kpi, src, focus, from=card, card). */
export function rankingLinkOf(card: Pick<CardSummary, "id" | "family" | "section" | "metric" | "scope">): RankingLink {
  const raw = card.section ?? card.metric.key;
  const kpi = KPI_KEYS.has(raw) ? raw : (KPI_OF_METRIC[raw] ?? KPI_OF_METRIC[card.metric.key] ?? (KPI_KEYS.has(card.metric.key) ? card.metric.key : "gmv"));
  return { kpi, src: SRC_OF_FAMILY[card.family], focus: card.scope.product_ids[0] ?? card.metric.critical_id ?? null, from: "card", card: card.id };
}

// ── The two layers of five numbers ──────────────────────────────────────────

export interface NumberRow {
  readonly key: "disc" | "eff" | "bien" | "orders" | "aov";
  readonly label: string;
  readonly before: string;
  readonly after: string;
  /** Change in VND (or the unit of the row). */
  readonly dv: string;
  /** Change in %. */
  readonly dp: string;
  readonly tone: Tone;
}

const num = (n: N | undefined): n is number => typeof n === "number" && Number.isFinite(n);
const toneOf = (c: Chip): Tone => (c.up === false ? "down" : c.up ? "up" : "flat");

function rangeText(lo: N, hi: N, f: (n: number) => string): string {
  if (!num(lo) || !num(hi)) return DASH;
  const a = Math.min(lo, hi);
  const b = Math.max(lo, hi);
  return Math.abs(a - b) < 1e-9 ? f(a) : `${f(a)} – ${f(b)}`;
}

const dOrders = (n: number) => `${n < 0 ? "−" : "+"}${fmt(Math.abs(n), 0)} đơn`;
const signedPct = (n: number) => `${n < 0 ? "−" : "+"}${fmt(Math.abs(n), 0)}%`;

/** Chi thêm over the card's effect window: the voucher's `extra_cost`, else the five numbers' extra spend. */
function extraSpend(card: Card): N {
  const c = card.certain;
  if (num(c.extra_cost)) return c.extra_cost;
  return card.five_numbers?.extra_revenue_per_extra_spend.extra_spend ?? null;
}

/**
 * "Chắc chắn": recomputed from the shop's real orders, buyers behaving as before. Number ② is never
 * taken from here (it needs volume): the row shows the break-even extra orders instead, and never a
 * red "0đ / 1đ".
 */
export function sureRows(card: Card): NumberRow[] {
  const f = card.five_numbers;
  if (!f) return []; // listing kinds carry no five numbers
  const compare = f.comparison.available;
  const d = f.discount;
  const discChip = compare ? chipPt(d.pct_before, d.pct_after) : { text: DASH, up: null, r: 0 };
  const m = f.margin;
  const marginChip = compare ? chipPt(m.pct_before, m.pct_after) : { text: DASH, up: null, r: 0 };
  const dProfit = num(m.profit_before) && num(m.profit_after) && !m.is_partial ? sv(m.profit_after - m.profit_before) : DASH;
  const o = f.orders;
  const a = f.aov;
  const spend = extraSpend(card);
  const be = card.certain.break_even_extra_orders;
  let eff: Pick<NumberRow, "after" | "dv" | "tone">;
  if (num(spend) && spend > 0) {
    eff = {
      after: num(be) ? `Hoà vốn khi thêm ≥ ${fmt(be, 0)} đơn` : "Cần đơn thêm để hoà vốn",
      dv: `chi thêm ${vnd(spend)}`,
      tone: "flat",
    };
  } else if (num(spend) && spend < 0) {
    eff = { after: `Giảm chi ${vnd(-spend)}`, dv: num(be) ? `còn lời nếu mất ≤ ${fmt(Math.abs(be), 0)} đơn` : "", tone: "up" };
  } else {
    eff = { after: "Không đổi chi", dv: DASH, tone: "flat" };
  }
  return [
    {
      key: "disc",
      label: FIVE_LABELS[0],
      before: pp(d.pct_before, 1),
      after: pp(d.pct_after, 1),
      dv: num(d.vnd_before) && num(d.vnd_after) ? sv(d.vnd_after - d.vnd_before) : DASH,
      dp: discChip.text,
      tone: discChip.r > 0.05 ? "down" : discChip.r < -0.05 ? "up" : "flat",
    },
    { key: "eff", label: FIVE_LABELS[1], before: DASH, after: eff.after, dv: eff.dv, dp: "", tone: eff.tone },
    { key: "bien", label: FIVE_LABELS[2], before: pp(m.pct_before, 1), after: pp(m.pct_after, 1), dv: dProfit, dp: marginChip.text, tone: toneOf(marginChip) },
    {
      key: "orders",
      label: FIVE_LABELS[3],
      before: num(o.before) ? fmt(o.before, 0) : DASH,
      after: num(o.after) ? fmt(o.after, 0) : DASH,
      dv: num(o.before) && num(o.after) ? dOrders(o.after - o.before) : DASH,
      dp: compare ? chipFromChange(o.change_pct).text : DASH,
      tone: compare ? toneOf(chipFromChange(o.change_pct)) : "flat",
    },
    {
      key: "aov",
      label: FIVE_LABELS[4],
      before: vnd(a.before),
      after: vnd(a.after),
      dv: num(a.before) && num(a.after) ? sv(a.after - a.before) : DASH,
      dp: compare ? chipFromChange(a.change_pct).text : DASH,
      tone: compare ? toneOf(chipFromChange(a.change_pct)) : "flat",
    },
  ];
}

const atP = (card: Card, q: "p10" | "p50" | "p90"): MoneyAt => card.predicted.money_per_month.total[q];

/** "Dự kiến": ranges (P10 – P90) per month on top of the certain layer; a range, not a promise. */
export function expectedRows(card: Card): NumberRow[] {
  if (!card.five_numbers) return [];
  const sure = sureRows(card);
  const pm = card.predicted.money_per_month;
  const lo = atP(card, "p10");
  const hi = atP(card, "p90");
  const f = card.five_numbers;
  const dchi = pm.certain.dchi;
  const net = card.certain.predicted_net;
  let eff: string;
  if (num(net?.extra_revenue_per_extra_spend_low) && num(net?.extra_revenue_per_extra_spend_high)) {
    eff = `${rangeText(net.extra_revenue_per_extra_spend_low, net.extra_revenue_per_extra_spend_high, (x) => `${fmt(x, 2)}đ`)} / 1đ chi`;
  } else if (num(dchi) && dchi > 0 && num(lo.dgmv) && num(hi.dgmv)) {
    eff = `${rangeText(lo.dgmv / dchi, hi.dgmv / dchi, (x) => `${fmt(x, 2)}đ`)} / 1đ chi`;
  } else if (num(dchi) && dchi <= 0) {
    eff = "giảm chi";
  } else {
    eff = DASH;
  }
  const ordersBefore = f.orders.before;
  const [disc, , bien, , aov] = sure;
  return [
    disc!,
    { key: "eff", label: FIVE_LABELS[1], before: DASH, after: eff, dv: `${rangeText(lo.dgmv, hi.dgmv, sv)} GMV`, dp: "", tone: "flat" },
    { ...bien!, dv: `${rangeText(lo.dprofit, hi.dprofit, sv)} trong ${fmt(pm.period?.days ?? pm.days, 0)} ngày` },
    {
      key: "orders",
      label: FIVE_LABELS[3],
      before: num(ordersBefore) ? fmt(ordersBefore, 0) : DASH,
      after: num(ordersBefore) && num(lo.dorders) && num(hi.dorders) ? rangeText(ordersBefore + lo.dorders, ordersBefore + hi.dorders, (x) => fmt(x, 0)) : DASH,
      dv: rangeText(lo.dorders, hi.dorders, dOrders),
      dp: num(ordersBefore) && ordersBefore > 0 && num(lo.dorders) && num(hi.dorders) ? rangeText((lo.dorders / ordersBefore) * 100, (hi.dorders / ordersBefore) * 100, signedPct) : DASH,
      tone: num(lo.dorders) && lo.dorders < 0 ? "down" : "up",
    },
    aov!,
  ];
}

// ── Floors and spend cap ────────────────────────────────────────────────────

export const FLOOR_KIND_LABEL: Readonly<Record<string, string>> = { operating: "giá sàn vận hành", absolute: "giá sàn tuyệt đối" };

export function breachLine(b: FloorBreach): string {
  const floor = num(b.floor) ? b.floor : null;
  const paid = num(b.min_unit_price) ? b.min_unit_price : null;
  const kind = FLOOR_KIND_LABEL[b.kind] ?? "giá sàn";
  const short = floor !== null && paid !== null ? ` (thiếu ${vnd(floor - paid)})` : "";
  return `${b.sku}: khách trả ${vnd(paid)} thấp hơn ${kind} ${vnd(floor)}${short}${b.kind === "absolute" ? ": đang lỗ." : "."}`;
}

const stepFloor = (value: number, step: number) => Math.floor(value / step) * step;

/**
 * The one-tap "Đặt về mức tối đa": the input values that end the worst breach, or `null` when the
 * card has no single input to pull back (the server still decides whether the floor holds).
 */
export function maxInputsFor(card: Card): Readonly<Record<string, number>> | null {
  const breaches = card.floor.breaches.filter((b) => num(b.floor) && num(b.min_unit_price));
  if (breaches.length === 0) return null;
  const shortfall = Math.max(...breaches.map((b) => (b.floor as number) - (b.min_unit_price as number)));
  if (!(shortfall > 0)) return null;
  const sliders = new Map(card.whatif.sliders.map((s) => [s.key, s]));
  const step = (key: string) => sliders.get(key)?.step ?? (key === "max_value" ? 1000 : 1);
  const inputs = card.inputs;
  if (card.family === "voucher") {
    const key = typeof inputs["pct"] === "number" && typeof inputs["max_value"] === "number" ? "max_value" : "value";
    const cur = inputs[key];
    if (typeof cur !== "number") return null;
    return { [key]: Math.max(0, stepFloor(cur - shortfall, step(key))) };
  }
  if ((card.family === "promotion" || card.family === "sale") && typeof inputs["discount_pct"] === "number") {
    const skus = (card.change.before["skus"] ?? []) as readonly { price?: number }[];
    const price = skus.find((s) => typeof s.price === "number")?.price;
    if (!price) return null;
    return { discount_pct: Math.max(0, stepFloor((inputs["discount_pct"] as number) - (shortfall / price) * 100, step("discount_pct"))) };
  }
  return null;
}

/** Cap line: "Chi marketing / ngày …" from the card's spend check. */
export function spendLine(card: Card): { readonly text: string; readonly over: boolean } | null {
  const s = card.spend;
  if (!s || !num(s.shop_chi_per_day_after)) return null;
  const over = s.over_cap === true;
  const cap = num(s.cap) ? `trần ${vnd(s.cap)}/ngày` : "chưa đặt trần";
  const delta = num(s.card_dchi_per_day) ? ` (thẻ này ${sv(s.card_dchi_per_day)}/ngày)` : "";
  return { text: `Chi marketing/ngày sau thẻ ${vnd(s.shop_chi_per_day_after)}${delta}, ${over ? "vượt" : "trong"} ${cap}.`, over };
}

// ── What-if inputs ──────────────────────────────────────────────────────────

/** Display of a slider value in its unit. */
export function sliderText(s: Pick<SliderRow, "unit">, value: number): string {
  switch (s.unit) {
    case "vnd":
      return vnd(value);
    case "pct":
      return `${fmt(value, value % 1 === 0 ? 0 : 1)}%`;
    case "days":
      return `${fmt(value, 0)} ngày`;
    case "roas":
      return fmt(value, 1);
    default:
      return fmt(value, 0);
  }
}

/** The value of a what-if input now: the pending edit, else the card's input, else the default. */
export function inputValue(card: Card, key: string): N {
  const v = card.inputs[key];
  return typeof v === "number" ? v : null;
}

/** Inputs that differ from the card as proposed (what "Phê duyệt" and "Yêu cầu chỉnh" carry). */
export function changedInputs(base: Readonly<Record<string, unknown>>, now: Readonly<Record<string, unknown>>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(now)) if (JSON.stringify(base[k] ?? null) !== JSON.stringify(v ?? null)) out[k] = v;
  return out;
}

/** "Giá trị đang xem" in one sentence, for the approve button and the request note. */
export function describeInputs(card: Card, sliders: readonly SliderRow[]): string {
  const parts: string[] = [];
  if (card.family === "voucher" && typeof card.inputs["pct"] === "number") {
    parts.push(`${fmt(card.inputs["pct"] as number, 0)}%${typeof card.inputs["max_value"] === "number" ? ` (tối đa ${vnd(card.inputs["max_value"] as number)})` : ""}`);
  }
  for (const s of sliders) {
    if (card.family === "voucher" && s.key === "max_value" && typeof card.inputs["pct"] === "number") continue;
    const v = card.inputs[s.key];
    if (typeof v === "number") parts.push(`${s.label.toLowerCase()} ${sliderText(s, v)}`);
  }
  return parts.join(", ");
}

// ── Read-back, measurement ──────────────────────────────────────────────────

export type ReadbackState = "none" | "pending" | "verified" | "mismatch" | "not_seen";

export interface Readback {
  readonly state: ReadbackState;
  readonly executedAt: string | null;
  /** Value the Connector saw (verified: the matching one; mismatch: the latest). */
  readonly observed: string | null;
  readonly observedAt: string | null;
}

export const READBACK_LABEL: Readonly<Record<ReadbackState, string>> = {
  none: "",
  pending: "Chờ xác minh",
  verified: "Đã xác minh",
  mismatch: "Không khớp",
  not_seen: "Chưa thấy",
};

function text(v: unknown): string | null {
  if (typeof v === "string") return v;
  if (typeof v === "number") return fmt(v, 0);
  if (v && typeof v === "object") {
    const parts = Object.entries(v as Record<string, unknown>).map(([k, x]) => `${k}: ${typeof x === "number" ? fmt(x, 0) : String(x)}`);
    return parts.length > 0 ? parts.join(", ") : null;
  }
  return null;
}

/** The read-back state of "Đã làm", from the card's events (`executed`, then `verified` / `mismatch` / `not_seen`). */
export function readbackOf(journey: readonly JourneyEvent[]): Readback {
  const executed = journey.filter((e) => e.event === "executed");
  if (executed.length === 0) return { state: "none", executedAt: null, observed: null, observedAt: null };
  const executedAt = executed[executed.length - 1]!.at;
  const outcomes = journey.filter((e) => (e.event === "verified" || e.event === "mismatch" || e.event === "not_seen") && e.at >= executedAt);
  const last = outcomes[outcomes.length - 1];
  if (!last) return { state: "pending", executedAt, observed: null, observedAt: null };
  const p = last.payload ?? {};
  return {
    state: last.event as ReadbackState,
    executedAt,
    observed: text(p["observed"] ?? p["observed_value"] ?? p["value"]),
    observedAt: typeof p["observed_at"] === "string" ? (p["observed_at"] as string) : last.at,
  };
}

export interface Reading {
  readonly label: string;
  readonly at: string;
  readonly impactPct: number | null;
  readonly confidence: string | null;
  readonly reason: string | null;
}

/** Interim (ngày 7) and final readings the measurement job logged, when they exist. */
export function readingsOf(journey: readonly JourneyEvent[]): { readonly t7: Reading | null; readonly final: Reading | null } {
  const read = (e: JourneyEvent | undefined, label: string): Reading | null => {
    if (!e) return null;
    const p = e.payload ?? {};
    return {
      label,
      at: e.at,
      impactPct: typeof p["impact_pct"] === "number" ? (p["impact_pct"] as number) : null,
      confidence: typeof p["confidence"] === "string" ? (p["confidence"] as string) : null,
      reason: typeof p["reason"] === "string" ? (p["reason"] as string) : null,
    };
  };
  return {
    t7: read(journey.find((e) => e.event === "impact_preliminary"), "Ngày 7"),
    final: read(journey.find((e) => e.event === "impact_final"), "Kết quả cuối"),
  };
}

export interface Countdown {
  /** "khó kết luận" | "Còn 9 ngày" | "Đã đủ 14 ngày" | "Đồng hồ chạy khi được xác minh". */
  readonly text: string;
  readonly daysLeft: number | null;
}

/** The measurement countdown: the plan's 14 / 28 days from the verified time, or "khó kết luận". */
export function countdownOf(plannedDays: number | null, readback: Readback, now: Date): Countdown {
  if (plannedDays === null) return { text: "khó kết luận", daysLeft: null };
  if (readback.state !== "verified" || !readback.observedAt) return { text: `Kết quả sau ${plannedDays} ngày · đồng hồ chạy khi thay đổi được xác minh`, daysLeft: null };
  const started = parseServerIso(readback.observedAt);
  const elapsed = Math.max(0, Math.floor((now.getTime() - started) / 86_400_000));
  const left = plannedDays - elapsed;
  return left > 0 ? { text: `Còn ${left} ngày (ngày ${Math.min(elapsed + 1, plannedDays)}/${plannedDays})`, daysLeft: left } : { text: `Đã đủ ${plannedDays} ngày`, daysLeft: 0 };
}

/** "09/11 14:05" in Vietnam time from a server timestamp (UTC when it carries no offset). */
export function vnWhen(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const t = parseServerIso(iso);
  if (!Number.isFinite(t)) return DASH;
  const parts = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "Asia/Ho_Chi_Minh" }).formatToParts(new Date(t));
  const get = (type: string) => parts.find((x) => x.type === type)?.value ?? "";
  return `${get("day")}/${get("month")} ${get("hour")}:${get("minute")}`;
}

export function stepText(v: string | number | null | undefined, unit?: string | null): string {
  if (v === null || v === undefined || v === "") return DASH;
  if (typeof v === "number") return unit === "VND" ? vnd(v) : unit === "%" ? `${fmt(v, 0)}%` : `${fmt(v, 0)}${unit ? ` ${unit}` : ""}`;
  return v;
}

/** Statuses Ops can take a card off the list from ("Gỡ thẻ"); a planned card leaves its draft plan first. */
export const WITHDRAWABLE: readonly string[] = ["draft", "sent", "changes_requested", "approved", "planned"];
