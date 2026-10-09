/**
 * Đề xuất grouping (AC-8.7, ADR-109 d.6/d.10) — pure.
 *
 * Optimize Product cards (`GET /v1/demo/decisions`, P7-B `diagnosis`) are
 * grouped by stream (the diagnosis' `channel_scope`) and weak stage
 * (`stage.code`: card → CTR, page → CTOR, basket → AOV). The group header
 * shows only what the backend gives: the sum of the cards' rule-based
 * recoverable GMV/day × 30 ("GMV dự kiến … /tháng", ước tính theo quy tắc).
 * The backend has no group target rate, so none is shown.
 *
 * Price / promotion cards (D13: recommendation only) and any card the backend
 * marks non-executable stay in their group with "Bạn áp dụng trên Seller
 * Center" and are never part of "Duyệt N thẻ".
 */

import type { DemoDecisionItem } from "@juli/contracts";

const STAGE_METRIC: Readonly<Record<string, string>> = {
  card: "CTR",
  page: "CTOR",
  basket: "AOV",
};

const STREAM_LABEL: Readonly<Record<string, string>> = {
  PRODUCT_CARD: "Thẻ sản phẩm",
  ALL_CHANNELS: "mọi kênh",
};

/** Levers Juli never executes itself (D13 price, promotions). */
export const MANUAL_LEVER_CODES: ReadonlySet<string> = new Set([
  "product_discount",
  "buy_more_save_more",
  "flash_sale",
  "shipping_discount",
  "price",
]);

export interface CompactCard {
  readonly id: string;
  /** TikTok product id, shown as the product code. */
  readonly code: string | null;
  readonly name: string;
  readonly mainKpi: string | null;
  readonly reason: string | null;
  /** What TikTok's own diagnosis says (Vietnamese detail), else Juli's local check. */
  readonly tiktokDiagnosis: string;
  readonly lever: string | null;
  readonly change: string | null;
  readonly recoverableGmvPerDay: number | null;
  /** Juli can execute it (counted in "Duyệt N thẻ"). */
  readonly executable: boolean;
  readonly item: DemoDecisionItem;
}

export interface DecisionGroup {
  readonly key: string;
  readonly streamLabel: string | null;
  readonly metric: string | null;
  readonly title: string;
  readonly cards: readonly CompactCard[];
  /** Σ recoverable GMV/day × 30, or null when no card carries one. */
  readonly gmvPerMonth: number | null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function diagnosisLine(item: DemoDecisionItem): string {
  const evidence = item.recommendation.diagnosis?.lever?.evidence ?? [];
  const tiktok = evidence
    .filter((entry) => entry.source === "tiktok")
    .map((entry) => text(entry.detail))
    .filter((detail): detail is string => detail !== null);
  if (tiktok.length > 0) return tiktok.join("; ");
  const local = evidence
    .filter((entry) => entry.source !== "tiktok")
    .map((entry) => text(entry.detail))
    .filter((detail): detail is string => detail !== null);
  if (local.length > 0) return `Không có mã TikTok · Juli kiểm: ${local.join("; ")}`;
  return "Không có mã chẩn đoán";
}

export function isManualCard(item: DemoDecisionItem): boolean {
  const lever = item.recommendation.diagnosis?.lever?.code;
  return !item.is_executable || (lever !== undefined && MANUAL_LEVER_CODES.has(lever));
}

export function toCompactCard(item: DemoDecisionItem): CompactCard {
  const diagnosis = item.recommendation.diagnosis ?? null;
  const impact = item.recommendation.expected_impact;
  return {
    id: item.id,
    code: text(diagnosis?.tiktok_product_id),
    name: text(diagnosis?.product_title) ?? item.title,
    mainKpi: text(diagnosis?.main_kpi?.label),
    reason: text(diagnosis?.trigger?.sentence) ?? text(item.description),
    tiktokDiagnosis: diagnosisLine(item),
    lever: text(diagnosis?.lever?.action) ?? text(diagnosis?.lever?.label),
    change: text(diagnosis?.lever?.detail),
    recoverableGmvPerDay:
      finite(diagnosis?.recoverable_gmv_per_day) ??
      (impact?.metric === "recoverable_gmv_per_day" ? finite(impact.value) : null),
    executable: !isManualCard(item),
    item,
  };
}

function groupKey(item: DemoDecisionItem): string {
  const diagnosis = item.recommendation.diagnosis;
  if (!diagnosis) return "other";
  return `${diagnosis.channel_scope ?? "ALL_CHANNELS"}:${diagnosis.stage?.code ?? "?"}`;
}

export function groupTitle(count: number, metric: string | null, stream: string | null): string {
  if (!metric) return `${count} đề xuất khác`;
  const where = stream === "mọi kênh" ? " (mọi kênh)" : stream ? ` ${stream}` : "";
  return `${count} thẻ tối ưu để nâng ${metric}${where}`;
}

/**
 * Groups in the backend's order (the first card of a group decides where the
 * group sits — the list arrives ranked by D22's recoverable GMV).
 */
export function groupDecisions(items: readonly DemoDecisionItem[]): DecisionGroup[] {
  const order: string[] = [];
  const buckets = new Map<string, DemoDecisionItem[]>();
  for (const item of items) {
    const key = groupKey(item);
    if (!buckets.has(key)) {
      order.push(key);
      buckets.set(key, []);
    }
    buckets.get(key)!.push(item);
  }
  return order.map((key) => {
    const members = buckets.get(key)!;
    const diagnosis = members[0].recommendation.diagnosis ?? null;
    const metric = diagnosis ? (STAGE_METRIC[diagnosis.stage?.code ?? ""] ?? text(diagnosis.main_kpi?.label)) : null;
    const scope = diagnosis?.channel_scope ?? "ALL_CHANNELS";
    const streamLabel = diagnosis ? (STREAM_LABEL[scope] ?? null) : null;
    const cards = members.map(toCompactCard);
    const perDay = cards
      .map((card) => card.recoverableGmvPerDay)
      .filter((value): value is number => value !== null);
    return {
      key,
      streamLabel,
      metric,
      title: groupTitle(cards.length, metric, streamLabel),
      cards,
      gmvPerMonth: perDay.length > 0 ? perDay.reduce((a, b) => a + b, 0) * 30 : null,
    };
  });
}

/** The cards "Duyệt N thẻ" runs: executable, not dropped, not already approved. */
export function batchCards(
  group: DecisionGroup,
  excluded: ReadonlySet<string>,
): CompactCard[] {
  return group.cards.filter((card) => card.executable && !excluded.has(card.id));
}
