/**
 * The one switch for a TikTok shop's old screens (W3 U-4, decision #8).
 *
 * A TikTok shop's Tổng quan and Phân tích are the shared screens (`/tong-quan`, `/phan-tich`, fed by the
 * analytics routes). The ADR-108 Trang chủ (`/`) and Phân tích (`/analytics`) stay reachable behind this
 * switch until LIVE passes; the follow-up then deletes `components/home/*`, `lib/shop-report/*` and this file.
 *
 * On when `NEXT_PUBLIC_TIKTOK_ADR108_SCREENS=1` (the whole build) or the page URL carries `?adr108=1`.
 */

export const TIKTOK_LEGACY_PARAM = "adr108";

export function tiktokLegacyScreens(search?: { get(name: string): string | null } | null): boolean {
  if (process.env.NEXT_PUBLIC_TIKTOK_ADR108_SCREENS === "1") return true;
  return search?.get(TIKTOK_LEGACY_PARAM) === "1";
}
