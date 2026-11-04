import { DASH, fmt, pc, vnd } from "../shopee-analytics/format";
import type { Plan, PlanAggregate, PlanSnapshot, StackBreach } from "./plan-types";
import type { N } from "./types";
import { MIN_MEASURE_DAYS, rangeK, roundK, svk } from "./versions";

/** What the Kế hoạch screen says about a {@link Plan} (artboard copy, Vietnamese). */

const num = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);
const mid = (a: N, b: N): N => (num(a) && num(b) ? (a + b) / 2 : null);
const MINUS = "−";

export const pts = (d: number): string => `${d >= 0 ? "+" : MINUS}${fmt(Math.abs(d * 100), 1)} điểm`;
const rangeOf = (a: N, b: N, f: (n: number) => string): string => {
  if (!num(a) || !num(b)) return DASH;
  const lo = Math.min(a, b);
  const hi = Math.max(a, b);
  return f(lo) === f(hi) ? f(lo) : `${f(lo)} – ${f(hi)}`;
};
const arrow = (d: number): string => (Math.abs(d) < 1e-9 ? "" : d > 0 ? "▲ " : "▼ ");

export interface AggRow {
  readonly key: string;
  readonly label: string;
  readonly today: string;
  readonly after: string;
  readonly d: string;
  readonly tone: "up" | "down" | "flat" | "plain";
  readonly bad?: boolean;
}

const toneOf = (good: 1 | -1, d: number): AggRow["tone"] => (Math.abs(d) < 1e-9 ? "flat" : d * good > 0 ? "up" : "down");

function eff(l: PlanSnapshot, t: PlanSnapshot): number | null {
  if (!num(l.spend_month) || !num(t.spend_month)) return null;
  const dc = l.spend_month - t.spend_month;
  return dc > 0 ? (l.gmv - t.gmv) / dc : null;
}

/** The plan's table: today -> after (a range, P10-P90), with the change in the middle of the range. */
export function aggRows(a: PlanAggregate): AggRow[] {
  const t = a.today;
  const lo = a.after.low;
  const hi = a.after.high;
  const rows: AggRow[] = [];
  const dDisc = (mid(lo.discount_rate, hi.discount_rate) ?? 0) - (t.discount_rate ?? 0);
  rows.push({ key: "disc", label: "① Giảm giá (% GMV niêm yết)", today: pc(t.discount_rate, 1), after: rangeOf(lo.discount_rate, hi.discount_rate, (x) => pc(x, 1)), d: pts(dDisc), tone: toneOf(-1, dDisc) });
  const e = [eff(lo, t), eff(hi, t)];
  rows.push({ key: "eff", label: "② Hiệu quả chi (ΔGMV ÷ Δchi)", today: DASH, after: e.every((x) => x === null) ? "giảm chi" : rangeOf(e[0] ?? 0, e[1] ?? 0, (x) => `${fmt(x, 2)}đ / 1đ chi`), d: "", tone: "plain" });
  const dBien = (mid(lo.margin, hi.margin) ?? 0) - (t.margin ?? 0);
  rows.push({ key: "bien", label: "③ Biên lợi nhuận", today: pc(t.margin, 1), after: rangeOf(lo.margin, hi.margin, (x) => pc(x, 1)), d: `${arrow(dBien)}${pts(dBien)}`, tone: toneOf(1, dBien) });
  const dOrd = (mid(lo.orders, hi.orders) ?? t.orders) - t.orders;
  rows.push({ key: "orders", label: "④ Số đơn / 30 ngày", today: fmt(t.orders, 0), after: rangeOf(Math.round(lo.orders), Math.round(hi.orders), (x) => fmt(x, 0)), d: `${dOrd >= 0 ? "+" : MINUS}${fmt(Math.abs(Math.round(dOrd)), 0)} đơn`, tone: toneOf(1, dOrd) });
  const dAov = (mid(lo.aov, hi.aov) ?? 0) - (t.aov ?? 0);
  rows.push({ key: "aov", label: "⑤ AOV", today: vnd(num(t.aov) ? roundK(t.aov) : null), after: rangeOf(lo.aov, hi.aov, (x) => vnd(roundK(x))), d: `${arrow(dAov)}${svk(dAov)}`, tone: toneOf(1, dAov) });
  rows.push({ key: "gmv", label: "GMV / 30 ngày", today: vnd(roundK(t.gmv)), after: rangeOf(lo.gmv, hi.gmv, (x) => vnd(roundK(x))), d: svk((mid(lo.gmv, hi.gmv) ?? t.gmv) - t.gmv), tone: "flat" });
  const dChi = (mid(lo.spend_month, hi.spend_month) ?? 0) - (t.spend_month ?? 0);
  rows.push({ key: "chi", label: "Chi phí / tháng", today: vnd(num(t.spend_month) ? roundK(t.spend_month) : null), after: vnd(num(mid(lo.spend_month, hi.spend_month)) ? roundK(mid(lo.spend_month, hi.spend_month)!) : null), d: svk(dChi), tone: toneOf(-1, dChi) });
  rows.push({ key: "chiday", label: "Chi phí toàn shop / ngày", today: vnd(a.spend.per_day_now), after: vnd(num(a.spend.per_day_after) ? roundK(a.spend.per_day_after) : null), d: a.spend.over_cap ? `Vượt trần ${vnd(a.spend.cap)}` : `Trong trần ${vnd(a.spend.cap)}`, tone: a.spend.over_cap ? "down" : "up", bad: a.spend.over_cap });
  rows.push({ key: "sure", label: "Δ lợi nhuận / tháng · chắc chắn", today: DASH, after: `${svk(a.dprofit_certain)}/tháng`, d: "", tone: num(a.dprofit_certain) ? (a.dprofit_certain >= 0 ? "up" : "down") : "plain" });
  const p = a.dprofit_month;
  rows.push({ key: "exp", label: "Δ lợi nhuận / tháng · dự kiến", today: DASH, after: `${rangeK(p.p10, p.p90)}/tháng`, d: "", tone: num(p.p10) && p.p10 >= 0 ? "up" : num(p.p90) && p.p90 <= 0 ? "down" : "plain" });
  const floorBad = !a.floor.ok;
  rows.push({ key: "floor", label: "Giá sàn", today: DASH, after: floorBad ? "✕ Có thẻ chạm giá sàn khi xếp chồng" : "✓ Mọi thẻ trên giá sàn vận hành", d: "", tone: floorBad ? "down" : "up", bad: floorBad });
  return rows;
}

/** "Chạm giá sàn khi xếp chồng": two cards that are each fine alone. */
export function stackWarning(w: StackBreach): { readonly title: string; readonly body: string; readonly fix: string } {
  const cards = w.cards.map((c) => `${c.code}-V${c.version} (${c.label})`);
  const alone = w.alone.map((a) => `${a.code} một mình ${vnd(a.buyer_pays)}`).join(", ");
  return {
    title: `Chạm giá sàn khi xếp chồng: ${w.product_name}`,
    body: `${cards.join(" và ")} cùng áp trên giỏ ${vnd(w.basket)}: khách trả ${vnd(w.buyer_pays)}, thấp hơn giá sàn vận hành ${vnd(w.floor)} (thiếu ${vnd(w.shortfall)}). Mỗi thẻ riêng lẻ đều đạt: ${alone}.`,
    fix: "Gỡ một trong hai thẻ, hoặc chọn mức thấp hơn, rồi kế hoạch mới xác nhận được.",
  };
}

/** The warnings the confirm dialog repeats: each stacked floor breach, each card under its floor, the spend cap. */
export function confirmWarnings(p: Plan): string[] {
  const out: string[] = [];
  for (const w of p.stack_breaches) out.push(`${w.product_name}: ${w.cards.map((c) => `${c.code}-V${c.version}`).join(" và ")} xếp chồng trên giỏ ${vnd(w.basket)}, khách trả ${vnd(w.buyer_pays)} thấp hơn giá sàn vận hành ${vnd(w.floor)}, thiếu ${vnd(w.shortfall)}.`);
  for (const c of p.cards) if (c.floor_breach && !c.stack_breach) out.push(`${c.code}-V${c.chosen_version}: chạm giá sàn.`);
  const s = p.aggregate?.spend;
  if (s?.over_cap && num(s.per_day_after) && num(s.cap)) out.push(`Trần chi: chi phí toàn shop ${vnd(Math.round(s.per_day_after))} / ngày vượt trần ${vnd(s.cap)} là ${vnd(Math.round(s.per_day_after - s.cap))} mỗi ngày.`);
  return out;
}

export const hasBreach = (p: Plan): boolean => confirmWarnings(p).length > 0;

export function cutText(c: Plan["cuts"][number]): string {
  const ok = c.done_days >= MIN_MEASURE_DAYS;
  return `${c.product_name}: đang đo ${c.code} (${c.kind_label}), mới ${c.done_days}/${c.total_days} ngày. Cắt hôm nay → ${ok ? `giữ kết quả “đo được ${c.done_days} ngày” (độ tin cậy thấp hơn).` : "“không kết luận” (dưới 3 ngày)."} Nhóm thay đổi mới bắt đầu đo.`;
}

/** "chỉ thấy thay đổi ≥ 45%" over the products of the plan. */
export function mdeText(by: Readonly<Record<string, number>> | undefined, productIds: readonly string[]): string {
  const v = productIds.map((id) => by?.[id]).filter(num).map((x) => Math.round(x));
  if (v.length === 0) return DASH;
  const a = Math.min(...v);
  const b = Math.max(...v);
  return a === b ? `≥ ${a}%` : `≥ ${a}–${b}%`;
}

export function windowText(p: Plan): string {
  const w = p.window;
  if (!w) return DASH;
  if (w.mode === "auto") return `tự động theo sản phẩm (${w.products.map((x) => `${x.product_name} ${x.recommended_days} ngày`).join(", ")})`;
  return `${w.mode} ngày`;
}

export function planProducts(p: Plan): string[] {
  return [...new Set(p.cards.map((c) => c.product_id).filter((x): x is string => !!x))];
}

/** Cards of a combo family drag the margin down and the basket up: say so. */
export function tradeoffText(p: Plan): string | null {
  const a = p.aggregate;
  if (!a || !p.cards.some((c) => c.kind_label.toLowerCase().startsWith("combo"))) return null;
  const dBien = (mid(a.after.low.margin, a.after.high.margin) ?? 0) - (a.today.margin ?? 0);
  const dAov = (mid(a.after.low.aov, a.after.high.aov) ?? 0) - (a.today.aov ?? 0);
  if (!(dBien < 0 && dAov > 0)) return null;
  return `thêm combo làm biên cả kế hoạch giảm ${fmt(Math.abs(dBien) * 100, 1)} điểm (còn ${pc(mid(a.after.low.margin, a.after.high.margin), 1)}) nhưng AOV tăng ${vnd(roundK(dAov))} và lợi nhuận dự kiến vẫn tăng. Bỏ combo thì biên cao hơn, AOV thấp hơn.`;
}

export function kolRows(k: NonNullable<Plan["kol"]>): { readonly k: string; readonly v: string }[] {
  return [
    { k: "Số thẻ", v: `${k.sample_cards} Gửi mẫu · ${k.invite_cards} Mời KOL` },
    { k: "Tổng chi phí mẫu (chắc chắn, chi một lần)", v: vnd(k.sample_cost) },
    { k: "Đơn dự kiến từ KOL", v: `${rangeOf(k.orders.p10, k.orders.p90, (x) => fmt(Math.round(x), 0)).replace(" – ", " – ")} đơn (ít dữ liệu: khoảng rộng)` },
    { k: "Lợi nhuận ròng sau mẫu, dự kiến", v: `${rangeK(k.profit_after_samples.p10, k.profit_after_samples.p90)}/tháng` },
    { k: "ROI gồm mẫu", v: rangeOf(k.roi.p10, k.roi.p90, (x) => pc(x, 0)) },
    { k: "Hoàn vốn mẫu", v: k.payback_orders ? `cần ≥ ${k.payback_orders} đơn từ KOL` : DASH },
  ];
}
