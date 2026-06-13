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

export function healthBarProgressPercent(current: number, max: number): number {
  if (max <= 0) {
    return 0;
  }
  return Math.min(100, Math.round((current / max) * 100));
}

/** Five-segment pink ramp for SPS (0–5) and AHR (0–1000). */
const HEALTH_RAMP_COLORS = [
  "#FCE8EE",
  "#F7CDDD",
  "#F2B2CC",
  "#EE98BB",
  "#E97DAA",
] as const;

export const SPS_SCALE_MAX = 5;
export const AHR_SCALE_MAX = 1000;
export const SPS_THRESHOLD_TICKS = [3.5, 4.5] as const;

export function healthRampColor(score: number, scaleMax: number): string {
  if (scaleMax <= 0 || score <= 0) {
    return HEALTH_RAMP_COLORS[0];
  }

  const normalized = Math.min(1, score / scaleMax);
  const bandIndex = Math.min(
    HEALTH_RAMP_COLORS.length - 1,
    Math.floor(normalized * HEALTH_RAMP_COLORS.length),
  );
  return HEALTH_RAMP_COLORS[bandIndex];
}

export function formatSpsThresholdLabel(tick: number): string {
  if (tick === 3.5) return "Mega-campaign";
  if (tick === 4.5) return "Star Shop";
  return String(tick);
}
