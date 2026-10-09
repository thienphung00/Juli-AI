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
import { compactVndNumber, fullDate, kpiPair, summariseText, upliftChip } from "./p10-format";
import type { CardStatus, LeverExecutor, P10DecisionItem, RecommendationCardPayload } from "./p10-types";

export const CARD_STATUS_LABELS: Readonly<Record<CardStatus, string>> = {
  pending: "Chờ duyệt",
  running: "Đang thực hiện",
  applied: "Đã áp dụng",
  rejected: "Đã từ chối",
  expired: "Hết hạn",
};

/** Executor chip + "what happens after Phê duyệt" (Levers.dc.html, verbatim). */
export const EXECUTOR_COPY: Readonly<Record<LeverExecutor, { chip: string; after: string; notice: string }>> = {
  juli: {
    chip: "Juli tự cập nhật sau khi bạn xác nhận",
    after: "Phê duyệt → lượt chạy → bạn xác nhận trước → sau → Juli ghi.",
    notice:
      "Đã tạo lượt chạy. Juli đọc chẩn đoán TikTok và soạn nội dung — bạn xác nhận lần cuối trước khi Juli ghi lên TikTok Shop.",
  },
  juli_with_photo: {
    chip: "Juli tải lên — cần ảnh từ bạn",
    after: "Phê duyệt → Juli hỏi ảnh → bạn tải ảnh → xác nhận → Juli thay ảnh bìa.",
    notice: "Đã tạo lượt chạy. Juli hỏi ảnh → bạn tải ảnh → xác nhận → Juli thay ảnh bìa.",
  },
  seller_center: {
    chip: "Bạn thực hiện trên Seller Center",
    after: 'Phê duyệt → Juli đưa hướng dẫn từng bước; bạn bấm "Đã áp dụng" để Juli bắt đầu đo.',
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
  readonly leverCode: string | null;
  readonly leverLabel: string | null;
  readonly executor: LeverExecutor;
  /** Built from the P10-A card (false = degraded from the P7-B diagnosis). */
  readonly fromContract: boolean;
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
  return `${sentence(full)} TikTok báo mã chẩn đoán: ${quoted}.`;
}

/** "Khách thêm giỏ rồi bỏ: Đơn/thêm giỏ … trung vị shop" (Mobile.dc.html). */
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
  const kpi = card.main_kpi;
  const sku = card.seller_sku ? `${card.seller_sku}${card.seller_sku_more > 0 ? ` +${card.seller_sku_more}` : ""}` : null;
  const reasonFull = reasonFullText(card);
  const updated = fullDate(card.updated_at);
  return {
    id: item.id,
    sku,
    title: card.product_title,
    meta: updated === "—" ? card.workflow_label : `${card.workflow_label} · Cập nhật ${updated}`,
    status: card.status,
    kpiLabel: kpi?.label ?? null,
    kpiCurrent: kpi ? kpiPair(kpi.current, kpi.target, kpi.unit).split(" → ")[0] : null,
    kpiTarget: kpi ? kpiPair(kpi.current, kpi.target, kpi.unit).split(" → ")[1] : null,
    kpiUplift: kpi ? upliftChip(kpi.current, kpi.target) : null,
    kpiPairText: kpi ? kpiPair(kpi.current, kpi.target, kpi.unit) : null,
    gmvPerMonth: gmvMonthText(card.expected_gmv_per_month),
    reasonShort: card.reason_short,
    reasonMobile: mobileReason(card.reason_short, card.reason_full),
    reasonFull,
    changeLabels: card.change_fields.map((field) => field.label),
    beforeAfter: card.before_after.map(beforeAfterView),
    gmvMethod: text(card.gmv_method),
    leverCode: card.lever.code,
    leverLabel: card.lever.label,
    executor: card.lever.executor,
    fromContract: true,
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
    leverCode: text(diagnosis?.lever?.code),
    leverLabel,
    executor: executorForLever(diagnosis?.lever?.code, item.is_executable),
    fromContract: false,
  };
}

export function cardView(item: P10DecisionItem): CardView {
  const card = item.recommendation.card;
  return card ? fromCard(item, card) : fromDiagnosis(item);
}
