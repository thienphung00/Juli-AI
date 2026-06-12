import type { ShopMetadata } from "@/lib/mock-data/operations/schemas";

/**
 * Canonical seller-facing metric definitions (P1.8).
 * SPS — probation graduation progress (Seller Center UI; mock in P1.8).
 * AHR — Account Health Rating per TikTok Shop policy (0–1,000 platform scale;
 * P1.8 mock uses graduation thresholds from probation fixtures).
 *
 * @see docs/tiktok_platform/seller/account-health.md
 * @see docs/system-design.md § SPS vs VP/AHR
 */
export const SPS_METRIC = {
  id: "sps",
  label: "SPS",
  fullLabel: "Shop Performance Score",
  description:
    "Điểm hiệu suất cửa hàng trong giai đoạn thử nghiệm — đo tiến độ tốt nghiệp so với ngưỡng TikTok Shop.",
} as const;

export const AHR_METRIC = {
  id: "ahr",
  label: "AHR",
  fullLabel: "Account Health Rating",
  description:
    "Điểm sức khỏe tài khoản (0–1.000 trên TikTok Shop) — càng cao càng khỏe; vi phạm làm giảm điểm.",
} as const;

export function resolveShopStatusLabel(metadata: ShopMetadata): string {
  if (metadata.profile === "NEW_SHOP" && metadata.probation_status === "active") {
    return "Đang thử nghiệm";
  }
  return "Hoạt động";
}

export function healthBarProgressPercent(current: number, target: number): number {
  if (target <= 0) {
    return 0;
  }
  return Math.min(100, Math.round((current / target) * 100));
}
