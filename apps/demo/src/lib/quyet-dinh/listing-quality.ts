import type { DiagnosisReading, ListingQuality } from "@juli/contracts";

import { vnDate, vnTime } from "./timeline";

/**
 * P71: Đo lường on the sandbox shop -- TikTok's own listing-quality diagnosis of a
 * listing edit, Ngày 0 (the run's "Đọc chẩn đoán TikTok" step) → now (re-read). Real
 * TikTok data; the sandbox still has no CTR / lượt xem / CTOR to measure. Pure.
 */

export const LISTING_QUALITY_LABEL = "Chất lượng trang sản phẩm (TikTok chấm)";
export const LISTING_QUALITY_CHIP = "Đo · TikTok chấm trang";
/** P76-5: TikTok's own check of the draft, asked right before Juli wrote it. */
export const LISTING_QUALITY_CHECKED_LABEL = "Sau sửa (TikTok kiểm tra)";
export const LISTING_QUALITY_NOTE =
  "Shop sandbox không có người mua thật nên Juli chỉ đo điểm TikTok chấm trang sản phẩm, không đo CTR, lượt xem hay doanh số.";

export interface ListingQualityView {
  /** "Chất lượng trang sản phẩm (TikTok chấm): 4 lỗi → 0 lỗi". */
  readonly headline: string;
  /** "Ngày 0: Tiêu đề quá ngắn, Mô tả quá ngắn"; null when Ngày 0 was not read. */
  readonly before: string | null;
  /**
   * P76-5: "Sau sửa (TikTok kiểm tra lúc 10:01 28/10/2026): TikTok không báo lỗi nào"; null when
   * the draft was not checked.
   */
  readonly checked: string | null;
  /**
   * "Bây giờ (đọc lúc 10:05 28/10/2026): TikTok không báo lỗi nào"; null when unread. An issue
   * TikTok's check had cleared arrives labelled "(TikTok chưa cập nhật chẩn đoán)" (P76-5).
   */
  readonly after: string | null;
  readonly tone: "ok" | "muted";
}

function errors(reading: DiagnosisReading | null, unread: string): string {
  return reading ? `${reading.count} lỗi` : unread;
}

function at(iso: string | null | undefined): string | null {
  return iso ? `${vnTime(iso).slice(0, 5)} ${vnDate(iso)}` : null;
}

function issues(reading: DiagnosisReading): string {
  if (reading.count === 0) return "TikTok không báo lỗi nào";
  const names = reading.issues.join(", ");
  const more = reading.count - reading.issues.length;
  return more > 0 ? `${names}${names ? " và " : ""}${more} lỗi khác` : names;
}

/** `null` when neither side was read: the panel then keeps its "không đo" line. */
export function listingQualityView(quality: ListingQuality | null | undefined): ListingQualityView | null {
  if (!quality || (!quality.before && !quality.after && !quality.checked)) return null;
  const { before, after } = quality;
  const checked = quality.checked ?? null;
  const readAt = at(after?.read_at);
  const checkedAt = at(checked?.read_at);
  const improved = (reading: DiagnosisReading | null) => !!before && !!reading && reading.count < before.count;
  return {
    headline: `${LISTING_QUALITY_LABEL}: ${errors(before, "chưa có số ngày 0")} → ${errors(after, "chưa đọc lại được")}`,
    before: before ? `Ngày 0: ${issues(before)}` : null,
    checked: checked ? `${LISTING_QUALITY_CHECKED_LABEL}${checkedAt ? ` lúc ${checkedAt}` : ""}: ${issues(checked)}` : null,
    after: after ? `Bây giờ${readAt ? ` (đọc lúc ${readAt})` : ""}: ${issues(after)}` : null,
    tone: improved(after) || improved(checked) ? "ok" : "muted",
  };
}
