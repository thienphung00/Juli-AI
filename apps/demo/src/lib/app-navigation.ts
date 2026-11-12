import { ACTIONS_DESTINATION_LABEL } from "./destination-copy";

/**
 * The app's four destinations (ADR-109 decision 7): Trang chủ / Quyết định /
 * Phân tích / Juli, in that order, as a left rail on desktop and a bottom bar
 * under 768px. Cài đặt is NOT a destination any more — it lives in the
 * shop-avatar menu in the header.
 *
 * Juli (the 24-hour activity log and the daily loop) is shown but LOCKED in
 * this phase: it has no route, renders as a non-link with `aria-disabled`,
 * and carries `JULI_LOCKED_HINT` as its tooltip.
 */

export type AppDestinationIcon = "home" | "decisions" | "analytics" | "juli" | "overview" | "products" | "keywords" | "ads" | "orders" | "flows";

export interface AppDestination {
  readonly key: AppDestinationIcon;
  readonly label: string;
  readonly icon: AppDestinationIcon;
  /** `null` for a locked destination — there is no page to navigate to. */
  readonly href: string | null;
  readonly locked: boolean;
  /** Other paths that belong to this destination (Xếp hạng opens from Tổng quan). */
  readonly alsoActive?: readonly string[];
}

export const JULI_LOCKED_HINT = "Sắp có: nhật ký 24 giờ";

export const APP_DESTINATIONS: readonly AppDestination[] = [
  { key: "home", label: "Trang chủ", icon: "home", href: "/", locked: false },
  {
    key: "decisions",
    label: ACTIONS_DESTINATION_LABEL,
    icon: "decisions",
    href: "/decisions",
    locked: false,
  },
  { key: "analytics", label: "Phân tích", icon: "analytics", href: "/analytics", locked: false },
  { key: "juli", label: "Juli", icon: "juli", href: null, locked: true },
];

/**
 * Shopee shops (ADR-120 decision 2): Tổng quan / Phân tích / Sản phẩm / Quyết định, in that
 * order, then (P92 B-8) the four read-only pages the seller has from Juli Ops: Từ khóa / Quảng cáo /
 * Đơn hàng / Luồng; Cài đặt stays in the avatar menu. Tổng quan replaces Trang chủ, and there is no locked
 * Juli entry. Isolated here so TikTok shops keep `APP_DESTINATIONS` untouched; the P81 app-shell
 * rework may fold the two lists into one.
 */
export const SHOPEE_DESTINATIONS: readonly AppDestination[] = [
  {
    key: "overview",
    label: "Tổng quan",
    icon: "overview",
    href: "/tong-quan",
    locked: false,
  },
  // P96b: /xep-hang redirects to /phan-tich (its product table); the entry stays lit for an old link.
  { key: "analytics", label: "Phân tích", icon: "analytics", href: "/phan-tich", locked: false, alsoActive: ["/xep-hang"] },
  { key: "products", label: "Sản phẩm", icon: "products", href: "/san-pham", locked: false },
  {
    key: "decisions",
    label: ACTIONS_DESTINATION_LABEL,
    icon: "decisions",
    href: "/decisions",
    locked: false,
  },
  { key: "keywords", label: "Từ khóa", icon: "keywords", href: "/tu-khoa", locked: false },
  { key: "ads", label: "Quảng cáo", icon: "ads", href: "/quang-cao", locked: false },
  { key: "orders", label: "Đơn hàng", icon: "orders", href: "/don-hang", locked: false },
  { key: "flows", label: "Luồng", icon: "flows", href: "/luong-san-pham", locked: false },
];

export type NavPlatform = "tiktok" | "shopee";

/**
 * P100 S2-C (owner, 2026-11-11): on the reviewer's sample shop ("Dữ liệu mẫu") the rail shows only
 * the screens that work there. The other Shopee pages are hidden (not greyed out, no "sắp có") and a
 * direct link to one goes to Tổng quan (`sampleShopRedirect`). The API refuses their routes on its
 * own (S2-F allowlist) — this list is presentation only.
 */
export const SAMPLE_SHOP_DESTINATION_KEYS: readonly AppDestinationIcon[] = ["overview", "analytics", "products", "decisions"];

export const SAMPLE_SHOP_HOME_HREF = "/tong-quan";

export const SAMPLE_SHOP_DESTINATIONS: readonly AppDestination[] = SHOPEE_DESTINATIONS.filter((d) =>
  SAMPLE_SHOP_DESTINATION_KEYS.includes(d.key),
);

export function destinationsFor(platform: NavPlatform, options: { readonly sampleShop?: boolean } = {}): readonly AppDestination[] {
  if (platform !== "shopee") return APP_DESTINATIONS;
  return options.sampleShop ? SAMPLE_SHOP_DESTINATIONS : SHOPEE_DESTINATIONS;
}

/**
 * Where a sample-shop reviewer is sent instead of `pathname`, or null to stay: the hidden Shopee
 * pages and Cài đặt (not in its avatar menu) go to Tổng quan.
 */
export function sampleShopRedirect(pathname: string): string | null {
  const hidden = [
    ...SHOPEE_DESTINATIONS.filter((d) => !SAMPLE_SHOP_DESTINATION_KEYS.includes(d.key)).map((d) => d.href),
    SETTINGS_HREF,
  ];
  return hidden.some((href) => isDestinationActive(pathname, href)) ? SAMPLE_SHOP_HOME_HREF : null;
}

export function isDestinationOn(pathname: string, destination: AppDestination): boolean {
  return (
    isDestinationActive(pathname, destination.href) ||
    (destination.alsoActive ?? []).some((path) => isDestinationActive(pathname, path))
  );
}

/** `/` is active only on itself; any other destination owns its sub-paths. */
export function isDestinationActive(pathname: string, href: string | null): boolean {
  if (!href) return false;
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** The shop-avatar menu's settings entry (was the fourth nav tab before ADR-109). */
export const SETTINGS_HREF = "/settings";
export const SETTINGS_LABEL = "Cài đặt";
export const CONNECT_SHOP_HREF = "/auth/connect-shop";

/** "Đăng nhập bằng email" (AC-9.1) — the shop-avatar menu's email item. */
export const EMAIL_SIGN_IN_HREF = "/auth/email";
