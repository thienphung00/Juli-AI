import { ACTIONS_DESTINATION_LABEL } from "./destination-copy";

/**
 * One rail for TikTok Shop and Shopee (owner, 2026-11-19): Tổng quan / Phân tích / Quyết định /
 * Dữ liệu shop, in that order, as a left rail on desktop and a bottom bar under 768px. Cài đặt is
 * not a destination — it lives in the shop-avatar menu in the header.
 *
 * Labels and order are shared; only the routes differ by platform. Shopee keeps its routes (the
 * Connector's "Mở Juli" links and the stock-alert email point at them). A TikTok shop's Tổng quan
 * is today's overview at `/`, and its Dữ liệu shop entry stays out until TikTok has those pages
 * (P101). Juli joins as the fourth entry on both platforms with its /juli page.
 */

export type AppDestinationIcon = "home" | "decisions" | "analytics" | "juli" | "overview" | "products" | "keywords" | "ads" | "orders" | "flows" | "data";

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

/** Tooltip of a locked entry; no entry is locked on either platform today. */
export const JULI_LOCKED_HINT = "Sắp có: nhật ký 24 giờ";

export type NavPlatform = "tiktok" | "shopee";

/** The other four Dữ liệu shop sub-tabs (Sản phẩm is the entry's own href). */
const DATA_SHOP_SUB_HREFS: readonly string[] = ["/tu-khoa", "/quang-cao", "/don-hang", "/luong-san-pham"];

interface RailEntry {
  readonly key: AppDestinationIcon;
  readonly label: string;
  /** The entry's route per platform; `null` leaves the entry off that platform's rail. */
  readonly href: Readonly<Record<NavPlatform, string | null>>;
  readonly alsoActive?: Partial<Readonly<Record<NavPlatform, readonly string[]>>>;
}

/** The single rail, in order. */
const RAIL: readonly RailEntry[] = [
  { key: "overview", label: "Tổng quan", href: { tiktok: "/", shopee: "/tong-quan" } },
  // P96b: /xep-hang redirects to /phan-tich (its product table); the entry stays lit for an old link.
  {
    key: "analytics",
    label: "Phân tích",
    href: { tiktok: "/analytics", shopee: "/phan-tich" },
    alsoActive: { shopee: ["/xep-hang"] },
  },
  { key: "decisions", label: ACTIONS_DESTINATION_LABEL, href: { tiktok: "/decisions", shopee: "/decisions" } },
  // P100 redesign: Sản phẩm / Từ khóa / Dịch vụ hiển thị / Đơn hàng / Luồng are sub-tabs of one entry.
  {
    key: "data",
    label: "Dữ liệu shop",
    href: { tiktok: null, shopee: "/san-pham" },
    alsoActive: { shopee: DATA_SHOP_SUB_HREFS },
  },
];

function railFor(platform: NavPlatform): readonly AppDestination[] {
  return RAIL.flatMap((entry) => {
    const href = entry.href[platform];
    if (href === null) return [];
    const alsoActive = entry.alsoActive?.[platform];
    return [{ key: entry.key, label: entry.label, icon: entry.key, href, locked: false, ...(alsoActive ? { alsoActive } : {}) }];
  });
}

/** A TikTok shop's rail. */
export const APP_DESTINATIONS: readonly AppDestination[] = railFor("tiktok");

/** A Shopee shop's rail (ADR-120 decision 2; its routes are unchanged). */
export const SHOPEE_DESTINATIONS: readonly AppDestination[] = railFor("shopee");

/**
 * P100 S2-C (owner, 2026-11-11): on the reviewer's sample shop ("Dữ liệu mẫu") the rail shows only
 * the screens that work there. The other Shopee pages are hidden (not greyed out, no "sắp có") and a
 * direct link to one goes to Tổng quan (`sampleShopRedirect`). The API refuses their routes on its
 * own (S2-F allowlist) — this list is presentation only.
 */
export const SAMPLE_SHOP_DESTINATION_KEYS: readonly AppDestinationIcon[] = ["overview", "analytics", "decisions", "data"];

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
 * pages, Cài đặt (not in its avatar menu) and `/` (the TikTok Trang chủ; P100 S2-D2) go to Tổng quan.
 */
export function sampleShopRedirect(pathname: string): string | null {
  // Dữ liệu shop: only its Sản phẩm sub-tab works on the sample shop; the other four go home.
  const hidden = [
    "/",
    ...SHOPEE_DESTINATIONS.filter((d) => !SAMPLE_SHOP_DESTINATION_KEYS.includes(d.key)).map((d) => d.href),
    ...DATA_SHOP_SUB_HREFS,
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
