/**
 * One recommendation card's view model (ADR-109 Amendment 1 d.1–3;
 * `Main.dc.html`, `Mobile.dc.html`, `Levers.dc.html`) — pure.
 *
 * Source: the P10-A `recommendation.card` (contract §1). Until P10-A is
 * merged a live item has no `card`, so the model degrades to the P7-B
 * diagnosis: no seller SKU chip, the KPI's current value only (no target —
 * the diagnosis gives none), recoverable GMV/day × 30, the trigger sentence
 * as the reason, the lever as the one changed field, no before → after.
 */

import { MANUAL_LEVER_CODES } from "./grouping";
import { SANDBOX_WRITTEN_LABEL, SIMULATED_RUN_LABEL } from "./simulated-copy";
import { compactVndNumber, countText, fullDate, kpiPair, pctNumber, summariseText, upliftChip } from "./p10-format";
import type {
  CardConfidence,
  CardGmvEstimate,
  CardKpiTarget,
  CardStatus,
  CardTargetMetric,
  LeverExecutor,
  P10DecisionItem,
  RecommendationCardPayload,
} from "./p10-types";

export const CARD_STATUS_LABELS: Readonly<Record<CardStatus, string>> = {
  pending: "Chờ duyệt",
  running: "Đang thực hiện",
  applied: "Đã áp dụng",
  simulated: SIMULATED_RUN_LABEL,
  rejected: "Đã từ chối",
  expired: "Hết hạn",
};

/** A card's status chip text; P64 (D73.4): on the reviewer's live sandbox shop a sandbox write is real. */
export function cardStatusLabel(status: CardStatus, sandboxShop = false): string {
  return status === "simulated" && sandboxShop ? SANDBOX_WRITTEN_LABEL : CARD_STATUS_LABELS[status];
}

/** Executor chip + "what happens after Duyệt" (Levers.dc.html, verbatim). */
export const EXECUTOR_COPY: Readonly<Record<LeverExecutor, { chip: string; after: string; notice: string }>> = {
  juli: {
    chip: "Juli tự cập nhật sau khi bạn xác nhận",
    after: "Duyệt → lượt chạy → bạn xác nhận trước → sau → Juli ghi.",
    notice:
      "Đã tạo lượt chạy. Juli đọc chẩn đoán TikTok và soạn nội dung. Bạn xác nhận lần cuối trước khi Juli ghi lên TikTok Shop.",
  },
  juli_with_photo: {
    chip: "Juli tải lên · cần ảnh từ bạn",
    after: "Duyệt → Juli hỏi ảnh → bạn tải ảnh → xác nhận → Juli thay ảnh bìa.",
    notice: "Đã tạo lượt chạy. Juli hỏi ảnh → bạn tải ảnh → xác nhận → Juli thay ảnh bìa.",
  },
  juli_drafts: {
    chip: "Juli soạn · bạn làm",
    after: "Duyệt → Juli đọc số liệu và soạn kịch bản → bạn chọn → bạn quay hoặc LIVE → Juli đo.",
    notice: "Đã tạo lượt chạy. Juli đọc số liệu và soạn kịch bản. Bạn xem, chọn rồi quay hoặc LIVE.",
  },
  seller_center: {
    chip: "Bạn thực hiện trên Seller Center",
    after: 'Duyệt → Juli đưa hướng dẫn từng bước; bạn bấm "Đã áp dụng" để Juli bắt đầu đo.',
    notice: 'Đã tạo lượt chạy. Juli đưa hướng dẫn từng bước; bạn bấm "Đã áp dụng" để Juli bắt đầu đo.',
  },
};

export const REJECTED_NOTICE = "Đã từ chối. Juli không thay đổi gì trên sản phẩm này.";

export interface BeforeAfterView {
  readonly field: string;
  readonly label: string;
  /** "strike": old struck / new bold (Tiêu đề). "summary": "Hiện tại: …" / "Đề xuất: …" (Mô tả). */
  readonly style: "strike" | "summary";
  readonly before: string;
  readonly after: string;
  /** Mobile one-liner: “old” → “new”, or "180 → 640 ký tự, …". */
  readonly inline: string;
}

/**
 * The content card's fact row label (ContentCards.dc.html; D24.2 makes it the
 * seller-facing word for a lever). The fact-row label, not the retired tab name.
 */
export const ACTION_ROW_LABEL = "Hành động";

/** P14-E content card extras (`ContentCards.dc.html`). */
export interface CardContentView {
  readonly kind: "video" | "live";
  /** The action chip in the action row ("Kịch bản video mới"). */
  readonly actionLabel: string;
  /** "Juli soạn · bạn làm". */
  readonly chip: string;
  /** "Juli sẽ soạn", one line per item (rendered pre-line). */
  readonly willDraft: string;
  /** "Đo kết quả". */
  readonly measure: string;
}

export interface CardView {
  readonly id: string;
  readonly sku: string | null;
  readonly title: string;
  readonly meta: string;
  readonly status: CardStatus;
  readonly kpiLabel: string | null;
  readonly kpiCurrent: string | null;
  readonly kpiTarget: string | null;
  readonly kpiUplift: string | null;
  /** "5,4 % → 5,9 %" for the mobile/levers layouts. */
  readonly kpiPairText: string | null;
  readonly gmvPerMonth: string | null;
  readonly reasonShort: string;
  readonly reasonMobile: string;
  readonly reasonFull: string | null;
  readonly changeLabels: readonly string[];
  readonly beforeAfter: readonly BeforeAfterView[];
  readonly gmvMethod: string | null;
  /** P14-B: rank adjusted by this shop's previous results ("đã điều chỉnh theo kết quả trước"). */
  readonly adjustedByHistory: boolean;
  /** P30 (D34.8): "Nhóm 6 sản phẩm đổi ảnh bìa: …" once the card's group has a verdict. */
  readonly groupResult?: string | null;
  readonly leverCode: string | null;
  readonly leverLabel: string | null;
  readonly executor: LeverExecutor;
  /** Built from the P10-A card (false = degraded from the P7-B diagnosis). */
  readonly fromContract: boolean;
  /** P14-E: set for a "Juli soạn · bạn làm" content card. */
  readonly content: CardContentView | null;
  /** P17 (D26): set for a quick-scan card ("Đề xuất nhanh · dựa trên 14 ngày", confidence "Tham khảo"). */
  readonly quickScan?: QuickScanView | null;
  /** P23 (D29.6): "Độ tin cậy: Cao / Vừa / Thấp" pill; absent on older payloads. */
  readonly confidence?: ConfidenceView | null;
  /** P23 (D29.1): the KPI's window, "30 ngày". */
  readonly kpiWindow?: string | null;
  /** P23 (D29.4): product + target metric, for grouping sibling cards. */
  readonly siblingKey?: string | null;
  /** "CTR" — the metric named in the group header "N thay đổi cho CTR". */
  readonly targetMetricLabel?: string | null;
  /** Other active cards of the same product + metric (0 = none). */
  readonly siblingCards?: number;
}

export interface ConfidenceView {
  readonly label: "Cao" | "Vừa" | "Thấp";
  /** Pill tone: green / amber / grey. */
  readonly tone: "ok" | "wait" | "muted";
}

const CONFIDENCE: Readonly<Record<CardConfidence, ConfidenceView>> = {
  high: { label: "Cao", tone: "ok" },
  medium: { label: "Vừa", tone: "wait" },
  low: { label: "Thấp", tone: "muted" },
};

export function confidenceView(value: unknown): ConfidenceView | null {
  return typeof value === "string" && value in CONFIDENCE ? CONFIDENCE[value as CardConfidence] : null;
}

export const TARGET_METRIC_LABELS: Readonly<Record<CardTargetMetric, string>> = {
  ctr: "CTR",
  ctor: "CTOR",
  aov: "AOV",
  impressions: "Lượt hiển thị",
};

type KpiUnit = "ratio" | "vnd" | "count";

function unitOfMetric(metric: string | null | undefined): KpiUnit {
  if (metric === "aov") return "vnd";
  if (metric === "impressions") return "count";
  return "ratio";
}

const isNum = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/** D32: seller copy for the channel a KPI is measured on (no backend terms). */
const KPI_CHANNEL_LABELS: Readonly<Record<string, string>> = {
  product_card: "đo trên kênh Thẻ sản phẩm",
  video: "đo trên kênh Video",
  live: "đo trên kênh LIVE",
  total: "đo trên tất cả kênh",
};

/** D32: "đo trên kênh Thẻ sản phẩm" / "đo trên tất cả kênh"; null for a card from before D32. */
export function kpiChannelText(channel: string | null | undefined): string | null {
  if (!channel) return null;
  return KPI_CHANNEL_LABELS[channel] ?? KPI_CHANNEL_LABELS.total;
}

/** P23 + D32: "30 ngày · đo trên kênh Thẻ sản phẩm"; the channel alone without a window. */
export function kpiWindowText(kpi: CardKpiTarget | null | undefined): string | null {
  const days = kpi?.window_days;
  const window = isNum(days) && days > 0 ? `${days} ngày` : null;
  const channel = kpiChannelText(kpi?.channel);
  if (window && channel) return `${window} · ${channel}`;
  return window ?? channel;
}

/** "3,8–4,4 %", "182k–205k ₫", "9.900–10.400". */
export function kpiRangeText(min: number, max: number, unit: KpiUnit): string {
  if (unit === "vnd") return `${compactVndNumber(min)}–${compactVndNumber(max)} ₫`;
  if (unit === "count") return `${countText(min)}–${countText(max)}`;
  return `${pctNumber(min)}–${pctNumber(max)} %`;
}

/** "▲ 18–37 %" from current to a target range. */
function upliftRange(current: number, min: number, max: number): string | null {
  const low = upliftChip(current, min);
  const high = upliftChip(current, max);
  if (!low || !high) return null;
  if (low === high) return low;
  if (low[0] !== high[0]) return null;
  return `${low.slice(0, -2)}–${high.slice(2)}`;
}

interface KpiTexts {
  readonly kpiCurrent: string;
  readonly kpiTarget: string;
  readonly kpiPairText: string;
  readonly kpiUplift: string | null;
}

/** P23 (D29.10): the band KPI as the card prints it; null keeps the main_kpi texts. */
export function kpiTargetTexts(kpi: CardKpiTarget | null | undefined, unitHint?: KpiUnit): KpiTexts | null {
  if (!kpi || !isNum(kpi.current)) return null;
  const unit = unitHint ?? unitOfMetric(kpi.metric);
  if (kpi.display === "range" && isNum(kpi.target_min) && isNum(kpi.target_max)) {
    const current = kpiPair(kpi.current, kpi.current, unit).split(" → ")[0];
    const target = kpiRangeText(kpi.target_min, kpi.target_max, unit);
    return {
      kpiCurrent: current,
      kpiTarget: target,
      kpiPairText: `${current} → ${target}`,
      kpiUplift: upliftRange(kpi.current, kpi.target_min, kpi.target_max),
    };
  }
  if (!isNum(kpi.target)) return null;
  const pair = kpiPair(kpi.current, kpi.target, unit);
  const [kpiCurrent, kpiTarget] = pair.split(" → ");
  return { kpiCurrent, kpiTarget, kpiPairText: pair, kpiUplift: upliftChip(kpi.current, kpi.target) };
}

function scaled(value: number, divisor: number, decimals: number): string {
  const [whole, fraction] = (Math.abs(value) / divisor).toFixed(decimals).split(".");
  const withDots = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return fraction ? `${withDots},${fraction}` : withDots;
}

/** P23 (D30.3): "+0,5–1,2 tr ₫/tháng" (one unit for both ends); a point when both round alike. */
export function gmvRangeText(estimate: CardGmvEstimate | null | undefined): string | null {
  if (!estimate || !isNum(estimate.per_month_min) || !isNum(estimate.per_month_max)) return null;
  const lo = Math.min(estimate.per_month_min, estimate.per_month_max);
  const hi = Math.max(estimate.per_month_min, estimate.per_month_max);
  const top = Math.max(Math.abs(lo), Math.abs(hi));
  const [divisor, decimals, suffix] = top >= 1e9 ? [1e9, 1, " tỷ"] : top >= 1e6 ? [1e6, 1, " tr"] : top >= 1e3 ? [1e3, 0, "k"] : [1, 0, ""];
  const fmt = (v: number) => `${v < 0 ? "−" : ""}${scaled(v, divisor, decimals)}`;
  const sign = lo >= 0 ? "+" : "";
  const a = fmt(lo);
  const b = fmt(hi);
  return `${sign}${a === b ? a : `${a}–${b}`}${suffix} ₫/tháng`;
}

export interface QuickScanView {
  readonly label: string;
  readonly confidence: string;
  readonly basis: string | null;
}

export function quickScanView(card: RecommendationCardPayload): QuickScanView | null {
  const quick = card.quick_scan;
  if (!quick || typeof quick !== "object") return null;
  const label = typeof quick.label === "string" && quick.label ? quick.label : "Đề xuất nhanh";
  const confidence = typeof quick.confidence === "string" && quick.confidence ? quick.confidence : "Tham khảo";
  return { label, confidence, basis: typeof quick.basis === "string" && quick.basis ? quick.basis : null };
}

export function contentView(card: RecommendationCardPayload): CardContentView | null {
  const content = card.content;
  if (!content) return null;
  return {
    kind: content.kind,
    actionLabel: content.action_label || card.lever.label,
    chip: content.chip || EXECUTOR_COPY.juli_drafts.chip,
    willDraft: content.will_draft.join("\n"),
    measure: content.measure,
  };
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function executorForLever(code: string | null | undefined, executable = true): LeverExecutor {
  if (!code) return executable ? "juli" : "seller_center";
  if (code === "cover_image" || code === "image" || code === "main_images") return "juli_with_photo";
  if (MANUAL_LEVER_CODES.has(code) || !executable) return "seller_center";
  return "juli";
}

function sentence(value: string): string {
  return /[.!?…]$/.test(value) ? value : `${value}.`;
}

function reasonFullText(card: RecommendationCardPayload): string {
  const full = card.reason_full.trim();
  const codes = card.tiktok_codes.filter((code) => code.trim());
  if (codes.length === 0 || full.includes("TikTok báo")) return full;
  const quoted = codes.map((code) => `“${code}”`).join(", ");
  return `${sentence(full)} TikTok báo: ${quoted}.`;
}

/** "Khách thêm giỏ rồi bỏ: Đơn/thêm giỏ … thấp hơn các sản phẩm tương tự trong shop" (Mobile.dc.html). */
function mobileReason(short: string, full: string | null): string {
  if (!full) return short;
  const clause = full.split(/ \(|\. /)[0].replace(/[.]$/, "").trim();
  return clause && clause !== short ? `${short}: ${clause}` : short;
}

function inlineChange(field: string, before: string, after: string): string {
  const b = summariseText(before, "before");
  const a = summariseText(after, "after");
  const lb = /^([\d.]+) ký tự(.*)$/.exec(b);
  const la = /^([\d.]+) ký tự(.*)$/.exec(a);
  if (lb && la) return `${lb[1]} → ${la[1]} ký tự${la[2]}`;
  if (field === "title" || (before.length <= 80 && after.length <= 80)) return `“${b}” → “${a}”`;
  return `${b} → ${a}`;
}

export function beforeAfterView(row: { field: string; label: string; before: string; after: string }): BeforeAfterView {
  const long = row.field === "description" || row.before.length > 80 || row.after.length > 80;
  return {
    field: row.field,
    label: row.label,
    style: long ? "summary" : "strike",
    before: long ? summariseText(row.before, "before") : row.before,
    after: long ? summariseText(row.after, "after") : row.after,
    inline: inlineChange(row.field, row.before, row.after),
  };
}

export function gmvMonthText(perMonth: number | null | undefined): string | null {
  if (perMonth === null || perMonth === undefined || !Number.isFinite(perMonth)) return null;
  return `${perMonth >= 0 ? "+" : ""}${compactVndNumber(perMonth)} ₫/tháng`;
}

function fromCard(item: P10DecisionItem, card: RecommendationCardPayload): CardView {
  // The backend may send a KPI without a current/target value (no readings yet).
  const kpi =
    card.main_kpi && typeof card.main_kpi.current === "number" && typeof card.main_kpi.target === "number"
      ? { ...card.main_kpi, current: card.main_kpi.current, target: card.main_kpi.target }
      : null;
  const sku = card.seller_sku ? `${card.seller_sku}${card.seller_sku_more > 0 ? ` +${card.seller_sku_more}` : ""}` : null;
  const reasonFull = reasonFullText(card);
  const updated = fullDate(card.updated_at);
  const band = kpiTargetTexts(card.kpi, card.main_kpi?.unit === "vnd" ? "vnd" : undefined);
  // A point KPI keeps today's main_kpi line; a range (or a card with no main_kpi) uses the band KPI.
  const bandKpi = band && (card.kpi?.display === "range" || !kpi) ? band : null;
  const metric = card.target_metric ?? card.kpi?.metric ?? null;
  const productKey =
    text(item.recommendation.diagnosis?.tiktok_product_id) ?? card.product_title ?? text(item.recommendation.diagnosis?.product_title);
  return {
    id: item.id,
    sku,
    title: card.product_title ?? text(item.recommendation.diagnosis?.product_title) ?? item.title,
    meta: updated === "—" ? card.workflow_label : `${card.workflow_label} · Cập nhật ${updated}`,
    status: card.status,
    kpiLabel: kpi?.label ?? card.main_kpi?.label ?? (bandKpi && metric ? (TARGET_METRIC_LABELS[metric] ?? null) : null),
    kpiCurrent: bandKpi ? bandKpi.kpiCurrent : kpi ? kpiPair(kpi.current, kpi.target, kpi.unit).split(" → ")[0] : null,
    kpiTarget: bandKpi ? bandKpi.kpiTarget : kpi ? kpiPair(kpi.current, kpi.target, kpi.unit).split(" → ")[1] : null,
    kpiUplift: bandKpi ? bandKpi.kpiUplift : kpi ? upliftChip(kpi.current, kpi.target) : null,
    kpiPairText: bandKpi ? bandKpi.kpiPairText : kpi ? kpiPair(kpi.current, kpi.target, kpi.unit) : null,
    gmvPerMonth: gmvRangeText(card.gmv_estimate) ?? gmvMonthText(card.expected_gmv_per_month),
    reasonShort: card.reason_short,
    reasonMobile: mobileReason(card.reason_short, card.reason_full),
    reasonFull,
    changeLabels: card.change_fields.map((field) => field.label),
    beforeAfter: card.before_after.map(beforeAfterView),
    gmvMethod: text(card.gmv_method),
    adjustedByHistory: card.adjusted_by_history === true,
    groupResult: text(card.group_result),
    leverCode: card.lever.code,
    leverLabel: card.lever.label,
    executor: card.content ? "juli_drafts" : card.lever.executor,
    fromContract: true,
    content: contentView(card),
    quickScan: quickScanView(card),
    confidence: confidenceView(card.confidence),
    kpiWindow: kpiWindowText(card.kpi),
    siblingKey: metric && productKey ? `${productKey}::${metric}` : null,
    targetMetricLabel: metric ? (TARGET_METRIC_LABELS[metric] ?? metric.toUpperCase()) : null,
    siblingCards: isNum(card.sibling_cards) && card.sibling_cards > 0 ? card.sibling_cards : 0,
  };
}

function fromDiagnosis(item: P10DecisionItem): CardView {
  const diagnosis = item.recommendation.diagnosis ?? null;
  const perDay =
    typeof diagnosis?.recoverable_gmv_per_day === "number"
      ? diagnosis.recoverable_gmv_per_day
      : item.recommendation.expected_impact?.metric === "recoverable_gmv_per_day"
        ? item.recommendation.expected_impact.value
        : null;
  const leverLabel = text(diagnosis?.lever?.label) ?? text(diagnosis?.lever?.action);
  const reason = text(diagnosis?.trigger?.sentence) ?? text(item.description) ?? "—";
  const updated = fullDate(item.surfaced_at ?? item.computed_at ?? diagnosis?.as_of ?? null);
  const workflow = text(item.recommendation.workflow_name) ?? "Tối ưu sản phẩm";
  return {
    id: item.id,
    sku: null,
    title: text(diagnosis?.product_title) ?? item.title,
    meta: updated === "—" ? workflow : `${workflow} · Cập nhật ${updated}`,
    status: "pending",
    kpiLabel: text(diagnosis?.main_kpi?.label),
    kpiCurrent: text(diagnosis?.main_kpi?.value),
    kpiTarget: null,
    kpiUplift: null,
    kpiPairText: text(diagnosis?.main_kpi?.value),
    gmvPerMonth: perDay === null ? null : gmvMonthText(perDay * 30),
    reasonShort: reason,
    reasonMobile: reason,
    reasonFull: text(diagnosis?.lever?.detail),
    changeLabels: leverLabel ? [leverLabel] : [],
    beforeAfter: [],
    gmvMethod: text(diagnosis?.recoverable_gmv_basis?.label),
    adjustedByHistory: false,
    leverCode: text(diagnosis?.lever?.code),
    leverLabel,
    executor: executorForLever(diagnosis?.lever?.code, item.is_executable),
    fromContract: false,
    content: null,
  };
}

export function cardView(item: P10DecisionItem): CardView {
  const card = item.recommendation.card;
  return card ? fromCard(item, card) : fromDiagnosis(item);
}

export type CardRun =
  | { readonly kind: "single"; readonly view: CardView }
  | {
      readonly kind: "siblings";
      readonly key: string;
      readonly title: string;
      /** "2 thay đổi cho CTR". */
      readonly countText: string;
      readonly views: readonly CardView[];
    };

/**
 * P23 (D29.4): cards with `sibling_cards > 0` that share a product + target
 * metric sit together under one product header, at the first one's place.
 * Approving each card stays separate. Without the field nothing moves.
 */
export function groupSiblings(views: readonly CardView[]): CardRun[] {
  const byKey = new Map<string, CardView[]>();
  for (const view of views) {
    if (!view.siblingKey || !view.siblingCards) continue;
    const list = byKey.get(view.siblingKey) ?? [];
    list.push(view);
    byKey.set(view.siblingKey, list);
  }
  const runs: CardRun[] = [];
  const placed = new Set<string>();
  for (const view of views) {
    const list = view.siblingKey ? byKey.get(view.siblingKey) : undefined;
    if (!list || list.length < 2) {
      runs.push({ kind: "single", view });
      continue;
    }
    if (placed.has(view.siblingKey!)) continue;
    placed.add(view.siblingKey!);
    runs.push({
      kind: "siblings",
      key: view.siblingKey!,
      title: view.title,
      countText: `${list.length} thay đổi cho ${view.targetMetricLabel ?? "chỉ số này"}`,
      views: list,
    });
  }
  return runs;
}
