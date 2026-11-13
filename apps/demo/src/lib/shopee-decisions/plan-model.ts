import { DASH, fmt, pp, vnCount, vnd } from "../shopee-analytics/format";
import type { Breach, N } from "./types";
import type { MeasurementCut, PlanBreach, PlanCard, PlanEvaluation, PlanResponse, WindowProductRow } from "./plan-types";
import { perDayText } from "../../components/shopee-decisions/option-card/format";
import { rangeK, roundK, svk } from "./versions";

/** What the Kế hoạch screen says about a {@link PlanResponse} (artboard copy, Vietnamese). */

const num = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);
const MINUS = "−";

/** Percent points as "+0,2 điểm". */
export const pts = (d: number): string => `${d >= 0 ? "+" : MINUS}${fmt(Math.abs(d), 1)} điểm`;
const rangeOf = (a: N, b: N, f: (n: number) => string): string => {
  if (!num(a) || !num(b)) return DASH;
  const lo = Math.min(a, b);
  const hi = Math.max(a, b);
  return f(lo) === f(hi) ? f(lo) : `${f(lo)} – ${f(hi)}`;
};
const arrow = (d: number): string => (Math.abs(d) < 1e-9 ? "" : d > 0 ? "▲ " : "▼ ");
const signed = (n: number, unit: string): string => `${n >= 0 ? "+" : MINUS}${vnCount(Math.abs(n))} ${unit}`;

export interface AggRow {
  readonly key: string;
  readonly label: string;
  readonly today: string;
  readonly after: string;
  readonly d: string;
  readonly tone: "up" | "down" | "flat" | "plain";
  readonly bad?: boolean;
}

/** P100: the plan's Δ are totals over its 30-day horizon; the secondary line is the same total per day. */
const perDay30 = (total: number): string => perDayText(total, 30) ?? "";

const toneOf = (good: 1 | -1, d: number): AggRow["tone"] => (Math.abs(d) < 1e-9 ? "flat" : d * good > 0 ? "up" : "down");

/** The plan's table, today -> after the plan (the backend's P50), with the P10 - P90 range where it gives one. */
export function aggRows(p: PlanResponse): AggRow[] {
  const a = p.aggregate;
  if (!a || a.data_missing || a.empty || a.n_cards === 0 || !a.today || !a.after || !a.cost || !a.dprofit_month || !a.dgmv_month || !a.dorders_month || !a.floor) return [];
  const t = a.today;
  const five = a.five_numbers ?? null;
  const rows: AggRow[] = [];

  if (five) {
    const d = five.discount;
    const dDisc = num(d.pct_before) && num(d.pct_after) ? d.pct_after - d.pct_before : null;
    rows.push({ key: "disc", label: "① Giảm giá (% GMV niêm yết)", today: pp(d.pct_before, 1), after: pp(d.pct_after, 1), d: dDisc === null ? DASH : pts(dDisc), tone: dDisc === null ? "plain" : toneOf(-1, dDisc) });
    const e = five.extra_revenue_per_extra_spend;
    rows.push({
      key: "eff",
      label: "② Hiệu quả chi (ΔGMV ÷ Δchi)",
      today: DASH,
      after: e.status === "giam_chi" ? "giảm chi" : num(e.per_vnd) ? `${fmt(e.per_vnd, 2)}đ / 1đ chi` : DASH,
      d: "",
      tone: "plain",
    });
    const m = five.margin;
    const dBien = num(m.pct_before) && num(m.pct_after) ? m.pct_after - m.pct_before : null;
    rows.push({ key: "bien", label: "③ Biên lợi nhuận", today: pp(m.pct_before, 1), after: pp(m.pct_after, 1), d: dBien === null ? DASH : `${arrow(dBien)}${pts(dBien)}`, tone: dBien === null ? "plain" : toneOf(1, dBien) });
  }

  const o = a.dorders_month;
  // The server's P50 only; never a subtraction of two other numbers (they may be on another basis).
  const dOrd = num(o.p50) ? o.p50 : null;
  rows.push({
    key: "orders",
    label: "④ Số đơn / 30 ngày",
    today: fmt(t.orders_30d, 0),
    after: rangeOf(num(o.p10) ? t.orders_30d + o.p10 : null, num(o.p90) ? t.orders_30d + o.p90 : null, (x) => fmt(Math.round(x), 0)),
    d: dOrd === null ? DASH : signed(dOrd, "đơn"),
    tone: dOrd === null ? "plain" : toneOf(1, dOrd),
  });
  const dAov = num(a.after.aov) && num(t.aov) ? a.after.aov - t.aov : null;
  rows.push({ key: "aov", label: "⑤ AOV", today: vnd(num(t.aov) ? roundK(t.aov) : null), after: vnd(num(a.after.aov) ? roundK(a.after.aov) : null), d: dAov === null ? DASH : `${arrow(dAov)}${svk(dAov)}`, tone: dAov === null ? "plain" : toneOf(1, dAov) });
  const g = a.dgmv_month.total;
  rows.push({
    key: "gmv",
    label: "GMV / 30 ngày",
    today: vnd(roundK(t.gmv_30d)),
    after: rangeOf(num(g.p10) ? t.gmv_30d + g.p10 : null, num(g.p90) ? t.gmv_30d + g.p90 : null, (x) => vnd(roundK(x))),
    d: num(g.p50) ? `${svk(g.p50)} · ${perDay30(g.p50)}` : svk(g.p50),
    tone: "flat",
  });
  const c = a.cost;
  const hz = c.horizon_spend_after !== undefined; // P99b: spend over the plan's horizon
  const known = c.cost_complete !== false;
  if (hz) {
    rows.push({
      key: "chi",
      label: "Chi phí trong 30 ngày tới",
      today: vnd(num(c.horizon_spend_before) ? roundK(c.horizon_spend_before) : null),
      after: known ? vnd(num(c.horizon_spend_after) ? roundK(c.horizon_spend_after) : null) : "chưa biết chi phí",
      d: known ? svk(c.horizon_spend_delta) : "",
      tone: known && num(c.horizon_spend_delta) ? toneOf(-1, c.horizon_spend_delta) : "plain",
    });
    const cap = c.horizon_cap;
    rows.push({
      key: "chiday",
      label: "Chi tiêu 30 ngày tới so với trần",
      today: vnd(num(c.horizon_spend_before) ? roundK(c.horizon_spend_before) : null),
      after: known ? vnd(num(c.horizon_spend_after) ? roundK(c.horizon_spend_after) : null) : "chưa biết chi phí",
      d: !num(cap) ? "Chưa đặt trần chi" : !known ? `Trần ${vnd(cap)}` : c.over_cap ? `Vượt trần ${vnd(cap)}` : `Trong trần ${vnd(cap)}`,
      tone: known && c.over_cap ? "down" : "plain",
      bad: known && c.over_cap,
    });
  } else {
    rows.push({
      key: "chi",
      label: "Chi phí / tháng",
      today: vnd(roundK(c.per_month_after - c.delta_per_month)),
      after: vnd(roundK(c.per_month_after)),
      d: svk(c.delta_per_month),
      tone: toneOf(-1, c.delta_per_month),
    });
    rows.push({
      key: "chiday",
      label: "Chi phí toàn shop / ngày",
      today: vnd(roundK(c.per_day_before)),
      after: vnd(roundK(c.per_day_after)),
      d: !num(c.cap_per_day) ? "Chưa đặt trần chi" : c.over_cap ? `Vượt trần ${vnd(c.cap_per_day)}` : `Trong trần ${vnd(c.cap_per_day)}`,
      tone: c.over_cap ? "down" : "up",
      bad: c.over_cap,
    });
  }
  const sure = a.dprofit_month.certain;
  rows.push({
    key: "sure",
    label: "Δ lợi nhuận cả 30 ngày · chắc chắn",
    today: DASH,
    after: num(sure) ? svk(sure) : `${DASH} (chưa tách được phần chắc chắn)`,
    d: num(sure) ? perDay30(sure) : "",
    tone: !num(sure) ? "plain" : sure >= 0 ? "up" : "down",
  });
  const q = a.dprofit_month.total;
  rows.push({ key: "exp", label: "Δ lợi nhuận cả 30 ngày · dự kiến", today: DASH, after: rangeK(q.p10, q.p90), d: num(q.p50) ? perDay30(q.p50) : "", tone: num(q.p10) && q.p10 >= 0 ? "up" : num(q.p90) && q.p90 <= 0 ? "down" : "plain" });
  const floorBad = !a.floor.ok;
  rows.push({ key: "floor", label: "Giá sàn", today: DASH, after: floorBad ? "✕ Có thẻ chạm giá sàn khi xếp chồng" : "✓ Mọi thẻ trên giá sàn vận hành", d: "", tone: floorBad ? "down" : "up", bad: floorBad });
  return rows;
}

const evalOf = (p: PlanResponse, cardId: string): PlanEvaluation | null => p.aggregate?.cards.find((c) => c.card_id === cardId) ?? p.cards.find((c) => c.card_id === cardId)?.evaluation ?? null;

/** A card that breaks a floor on its own. */
export const cardBreaches = (p: PlanResponse, c: PlanCard): boolean => (c.evaluation ?? evalOf(p, c.card_id))?.floor_ok === false;

/** A floor breach only the stack causes: no card breaches it alone. */
export const stackBreaches = (p: PlanResponse): readonly PlanBreach[] => (p.aggregate?.floor?.breaches ?? []).filter((b) => b.only_when_stacked === true);

/** Cards named by a breach: its owners, else every card stacked on the same orders. */
function breachCards(p: PlanResponse, b: PlanBreach): PlanCard[] {
  const ids = new Set<string>((b.card_ids ?? []).map((id) => id.split("@v")[0]!));
  if (ids.size === 0) for (const s of p.aggregate?.stacked_products ?? []) if (s.stacked_on_same_orders) for (const id of s.cards) ids.add(id);
  return p.cards.filter((c) => ids.has(c.card_id));
}

export const isStacked = (p: PlanResponse, c: PlanCard): boolean => stackBreaches(p).some((b) => breachCards(p, b).some((x) => x.card_id === c.card_id));

const versionLabel = (c: PlanCard): string => c.versions.find((v) => v.version === c.chosen_version)?.label ?? c.title ?? "";

/** "Chạm giá sàn khi xếp chồng": cards that are each fine alone but not together. */
export function stackWarning(p: PlanResponse, b: PlanBreach): { readonly title: string; readonly body: string; readonly fix: string } {
  const cards = breachCards(p, b);
  const names = [...new Set(cards.map((c) => productName(p, c.product_id)))];
  const list = cards.map((c) => `${c.code}-V${c.chosen_version} (${versionLabel(c)})`);
  const alone = cards.filter((c) => c.evaluation?.floor_ok !== false).map((c) => c.code);
  const short = num(b.floor) && num(b.min_unit_price) ? `, thiếu ${vnd(b.floor - b.min_unit_price)}` : "";
  return {
    title: `Chạm giá sàn khi xếp chồng${names.length > 0 ? `: ${names.join(", ")}` : ""}`,
    body: `${list.join(" và ")} cùng áp lên ${b.sku ?? "SKU"}: khách trả ${vnd(b.min_unit_price)}, thấp hơn giá sàn vận hành ${vnd(b.floor)}${short}.${alone.length > 0 ? ` Mỗi thẻ riêng lẻ đều đạt: ${alone.join(", ")}.` : ""}`,
    fix: "Gỡ một trong hai thẻ, hoặc chọn mức thấp hơn. Bạn vẫn xác nhận được, Juli hiện cảnh báo trước và ghi lại.",
  };
}

export function productName(p: PlanResponse, productId: string | null): string {
  if (!productId) return "Toàn shop";
  return p.aggregate?.products?.find((b) => b.product_id === productId)?.name ?? productId;
}

/** Everything the confirm dialog warns about: the aggregate's breaches (floor, spend cap), then any card's own. */
export function planBreaches(p: PlanResponse): readonly Breach[] {
  // P97 D85.14: the groups are judged on their own; their breaches warn too
  return [...(p.aggregate?.breaches ?? []), ...(p.groups ?? []).flatMap((g) => g.aggregate?.breaches ?? [])];
}

const floorLine = (b: Breach): string => {
  const short = num(b.floor) && num(b.min_unit_price) ? `, thiếu ${vnd(b.floor - b.min_unit_price)}` : "";
  return `Giá sàn: ${b.sku ?? "SKU"}, khách trả ${vnd(b.min_unit_price)} thấp hơn ${b.kind === "absolute" ? "giá sàn tuyệt đối" : "giá sàn vận hành"} ${vnd(b.floor)}${short}.`;
};

/** The warnings the confirm dialog repeats: each floor breach (stacked or not), the spend cap. */
export function confirmWarnings(p: PlanResponse): string[] {
  const out: string[] = [];
  for (const b of planBreaches(p)) {
    if (b.type === "floor") {
      const names = breachCards(p, b as PlanBreach).map((c) => `${c.code}-V${c.chosen_version}`);
      out.push(`${floorLine(b)}${names.length > 0 ? ` (${names.join(" và ")})` : ""}`);
    } else if (b.type === "spend_cap") {
      const after = num(b.spend_per_day_after) ? b.spend_per_day_after : null;
      const cap = num(b.cap) ? b.cap : null;
      out.push(`Trần chi: chi phí toàn shop ${vnd(after === null ? null : Math.round(after))} / ngày vượt trần ${vnd(cap)}${after !== null && cap !== null ? ` là ${vnd(Math.round(after - cap))} mỗi ngày` : ""}.`);
    }
  }
  return out;
}

export const hasBreach = (p: PlanResponse): boolean => planBreaches(p).length > 0;

/** What a running measurement keeps when the plan is executed today (the backend's own sentence). */
export function cutText(c: MeasurementCut): string {
  return `${c.name ?? c.product_id}: đang đo, mới ${c.days_measured}/${c.window_days} ngày. Cắt hôm nay → “${c.label.toLowerCase()}”${c.state === "inconclusive" ? " (dưới 3 ngày)" : " (độ tin cậy thấp hơn)"}. Nhóm thay đổi mới bắt đầu đo.`;
}

/** "chỉ thấy thay đổi ≥ 45%" over the products of the plan, for a preset of `days`. */
export function mdeText(rows: readonly WindowProductRow[], days: number): string {
  const v = rows.map((r) => r.options.presets.find((x) => x.days === days)?.mde_pct).filter(num).map((x) => Math.round(x));
  if (v.length === 0) return DASH;
  const a = Math.min(...v);
  const b = Math.max(...v);
  return a === b ? `≥ ${a}%` : `≥ ${a}–${b}%`;
}

/** The smallest change (%) the product's window can see, when the backend computed it for those days. */
export function productMde(r: WindowProductRow): number | null {
  const m = r.options.presets.find((x) => x.days === r.days)?.mde_pct;
  return num(m) ? Math.round(m) : null;
}

/** Shorter than the recommendation (or nothing reaches the limit): "khó kết luận", never refused. */
export function isHard(r: WindowProductRow): boolean {
  const preset = r.options.presets.find((x) => x.days === r.days);
  if (preset) return preset.hard;
  return r.recommended_days === null || r.days < r.recommended_days;
}

export function windowText(p: PlanResponse): string {
  const w = p.windows;
  const days = p.plan?.window_days ?? null;
  if (!w) return DASH;
  if (days === null) return `tự động theo sản phẩm (${w.per_product.map((x) => `${x.name ?? x.product_id} ${x.days} ngày`).join(", ")})`;
  return `${days} ngày`;
}

export function planProducts(p: PlanResponse): string[] {
  return [...new Set(p.cards.map((c) => c.product_id).filter((x): x is string => !!x))];
}

/** Cards of a combo family drag the margin down and the basket up: say so. */
export function tradeoffText(p: PlanResponse): string | null {
  const a = p.aggregate;
  if (!a?.after || !a.today || !a.five_numbers || !p.cards.some((c) => c.change_kind === "combo")) return null;
  const m = a.five_numbers.margin;
  const dBien = num(m.pct_before) && num(m.pct_after) ? m.pct_after - m.pct_before : 0;
  const dAov = num(a.after.aov) && num(a.today.aov) ? a.after.aov - a.today.aov : 0;
  if (!(dBien < 0 && dAov > 0)) return null;
  return `thêm combo làm biên cả kế hoạch giảm ${fmt(Math.abs(dBien), 1)} điểm (còn ${pp(m.pct_after, 1)}) nhưng AOV tăng ${vnd(roundK(dAov))} và lợi nhuận dự kiến vẫn tăng. Bỏ combo thì biên cao hơn, AOV thấp hơn.`;
}

/** "Bỏ thẻ này thì": the plan without the card, against the plan with it (the backend's `without.delta`). */
export function withoutText(c: PlanCard): string {
  const w = c.evaluation?.without;
  if (!w) return "kế hoạch chỉ còn thẻ này, bỏ đi là kế hoạch trống";
  const d = w.delta;
  return `lợi nhuận ${svk(num(d.dprofit_p50) ? -d.dprofit_p50 : null)} cả 30 ngày (${num(d.dprofit_p50) ? perDay30(-d.dprofit_p50) : DASH}), GMV ${svk(num(d.dgmv_p50) ? -d.dgmv_p50 : null)} cả 30 ngày (${num(d.dgmv_p50) ? perDay30(-d.dgmv_p50) : DASH}), chi phí ${svk(num(d.cost_month) ? -d.cost_month : null)} (30 ngày tới)`;
}

const KOL_KINDS = new Set(["affiliate_sample", "affiliate_invite"]);

/** The KOL cards of the plan as one block: counts, the sample cost (certain) and the expected profit after samples. */
export interface KolPlanSummary {
  readonly samples: number;
  readonly invites: number;
  readonly sampleCost: number | null;
  readonly profit: { readonly p10: number | null; readonly p50: number | null; readonly p90: number | null };
}

export function kolSummary(p: PlanResponse): KolPlanSummary | null {
  const cards = p.cards.filter((c) => c.change_kind !== null && KOL_KINDS.has(c.change_kind));
  if (cards.length === 0) return null;
  const evs = cards.map((c) => c.evaluation).filter((e): e is PlanEvaluation => e !== null);
  const sampleCost = evs.some((e) => !num(e.alone.dprofit.certain)) ? null : evs.reduce((s, e) => s - Math.min(0, e.alone.dprofit.certain as number), 0);
  const sum = (q: "p10" | "p50" | "p90"): number | null => (evs.some((e) => !num(e.alone.dprofit[q])) ? null : evs.reduce((s, e) => s + (e.alone.dprofit[q] as number), 0));
  const p50 = sum("p50");
  const spread = (q: "p10" | "p90"): number | null => {
    if (p50 === null || evs.some((e) => !num(e.alone.dprofit[q]) || !num(e.alone.dprofit.p50))) return null;
    const w = Math.sqrt(evs.reduce((s, e) => s + ((e.alone.dprofit[q] as number) - (e.alone.dprofit.p50 as number)) ** 2, 0));
    return q === "p10" ? p50 - w : p50 + w;
  };
  return { samples: cards.filter((c) => c.change_kind === "affiliate_sample").length, invites: cards.filter((c) => c.change_kind === "affiliate_invite").length, sampleCost, profit: { p10: spread("p10"), p50, p90: spread("p90") } };
}

export function kolRows(k: KolPlanSummary): { readonly k: string; readonly v: string }[] {
  return [
    { k: "Số thẻ", v: `${k.samples} Gửi mẫu · ${k.invites} Mời KOL` },
    { k: "Tổng chi phí mẫu (chắc chắn, chi một lần)", v: k.sampleCost === null ? `${DASH} (chưa tách được phần chắc chắn)` : vnd(k.sampleCost) },
    { k: "Lợi nhuận ròng sau mẫu, dự kiến", v: `${rangeK(k.profit.p10, k.profit.p90)}/tháng` },
  ];
}
