import { SELLER_COPY_BANNED_PATTERNS } from "@juli/contracts";

import type { RecommendationFixture } from "./recommendations";

export const REVIEW_STAGE_TITLES = {
  why: "Vì sao đề xuất này",
  analytics: "Bằng chứng từ Phân tích",
  inputs: "Thông tin cần xác nhận",
  preview: "Xem trước trước khi phê duyệt",
  approve: "Xác nhận phê duyệt",
} as const;

export const SELLER_APPROVE_STAGE_BODY =
  "Bạn sắp phê duyệt đề xuất này. Sau khi xác nhận, Juli mở luồng Đang thực hiện để bạn theo dõi tiến trình. Demo không gọi TikTok API thật.";

export const SELLER_APPROVE_GATE = {
  title: "Xác nhận phê duyệt",
  description:
    "Bạn có chắc muốn phê duyệt đề xuất này? Hành động sẽ chuyển sang Đang thực hiện.",
  confirmLabel: "Phê duyệt",
  cancelLabel: "Hủy",
} as const;

// Alias for backwards compatibility
export const REVIEW_UI_BANNED_PATTERNS = SELLER_COPY_BANNED_PATTERNS;

export function sanitizeSellerReviewText(text: string): string {
  return text
    .replace(/\bkho FBS\b/gi, "kho giao hàng")
    .replace(/\bSKU FBS\b/gi, "SKU trên kho giao hàng")
    .replace(/\bđơn hàng FBS\b/gi, "đơn hàng trên kho giao hàng")
    .replace(/\bFBS\b/g, "giao hàng của shop")
    .replace(/\bFBT\b/g, "giao hàng do TikTok quản lý")
    .replace(/`[^`]+`/g, "")
    .replace(/Unresolved\/Unfilled/gi, "chưa có trong Demo")
    .replace(/\bwebhook\b/gi, "thông báo cập nhật")
    .replace(/\bactivity_id\b/gi, "chương trình khuyến mãi")
    .replace(/\s{2,}/g, " ")
    .trim();
}

export function buildSellerWhyBody(
  fixture: Pick<
    RecommendationFixture,
    "reasoning" | "signal" | "evidence" | "risks"
  >,
): string {
  return [
    fixture.reasoning,
    fixture.signal,
    sanitizeSellerReviewText(fixture.evidence),
    fixture.risks,
  ].join("\n\n");
}

export function buildSellerPreviewBody(
  fixture: Pick<RecommendationFixture, "sellerReason" | "risks">,
  notes: string[] = [],
): string {
  const paragraphs = [
    `Tóm tắt: ${fixture.sellerReason}`,
    fixture.risks,
    ...notes,
  ].filter((paragraph) => paragraph.trim().length > 0);

  return paragraphs.join("\n\n");
}

export function buildSellerApproveBody(extraNotes: string[] = []): string {
  const paragraphs = [SELLER_APPROVE_STAGE_BODY, ...extraNotes].filter(
    (paragraph) => paragraph.trim().length > 0,
  );

  return paragraphs.join("\n\n");
}
