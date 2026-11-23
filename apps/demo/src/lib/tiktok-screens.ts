/**
 * The one switch for a TikTok shop's old screens (W3 U-4, decision #8).
 *
 * A TikTok shop's Tổng quan and Phân tích are the shared screens (`/tong-quan`, `/phan-tich`, fed by the
 * analytics routes), and the rail always links those. The ADR-108 Trang chủ (`/`) and Phân tích (`/analytics`)
 * stay reachable only when the page URL carries `?adr108=1` (the live comparison) until LIVE passes; the
 * follow-up then deletes `components/home/*`, `lib/shop-report/*` and this file.
 */

export const LEGACY_SCREENS_PARAM = "adr108";

export function tiktokLegacyScreens(search?: { get(name: string): string | null } | null): boolean {
  return search?.get(LEGACY_SCREENS_PARAM) === "1";
}
