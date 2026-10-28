import type { DiagnosisReading, ListingQuality } from "@juli/contracts";

import { vnDate, vnTime } from "./timeline";

/**
 * P71: Đo lường on the sandbox shop -- TikTok's own listing-quality diagnosis of a
 * listing edit, Ngày 0 (the run's "Đọc chẩn đoán TikTok" step) → now (re-read). Real
 * TikTok data; the sandbox still has no CTR / lượt xem / CTOR to measure. Pure.
 */

export const LISTING_QUALITY_LABEL = "Chất lượng trang sản phẩm (TikTok chấm)";
export const LISTING_QUALITY_CHIP = "Đo · TikTok chấm trang";
export const LISTING_QUALITY_NOTE =
  "Shop sandbox không có người mua thật nên Juli chỉ đo điểm TikTok chấm trang sản phẩm, không đo CTR, lượt xem hay doanh số.";

export interface ListingQualityView {
  /** "Chất lượng trang sản phẩm (TikTok chấm): 4 lỗi → 0 lỗi". */
  readonly headline: string;
  /** "Ngày 0: Tiêu đề quá ngắn, Mô tả quá ngắn"; null when Ngày 0 was not read. */
  readonly before: string | null;
  /** "Bây giờ (đọc lúc 10:05 28/10/2026): TikTok không báo lỗi nào"; null when unread. */
  readonly after: string | null;
  readonly tone: "ok" | "muted";
}

function errors(reading: DiagnosisReading | null, unread: string): string {
  return reading ? `${reading.count} lỗi` : unread;
}

function issues(reading: DiagnosisReading): string {
  if (reading.count === 0) return "TikTok không báo lỗi nào";
  const names = reading.issues.join(", ");
  const more = reading.count - reading.issues.length;
  return more > 0 ? `${names}${names ? " và " : ""}${more} lỗi khác` : names;
}

/** `null` when neither side was read: the panel then keeps its "không đo" line. */
export function listingQualityView(quality: ListingQuality | null | undefined): ListingQualityView | null {
  if (!quality || (!quality.before && !quality.after)) return null;
  const { before, after } = quality;
  const at = after?.read_at ? `${vnTime(after.read_at).slice(0, 5)} ${vnDate(after.read_at)}` : null;
  return {
    headline: `${LISTING_QUALITY_LABEL}: ${errors(before, "chưa có số ngày 0")} → ${errors(after, "chưa đọc lại được")}`,
    before: before ? `Ngày 0: ${issues(before)}` : null,
    after: after ? `Bây giờ${at ? ` (đọc lúc ${at})` : ""}: ${issues(after)}` : null,
    tone: before && after && after.count < before.count ? "ok" : "muted",
  };
}
