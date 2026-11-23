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

export type NavPlatform = "tiktok" | "shopee";

/** The other four Dữ liệu shop sub-tabs (Sản phẩm is the entry's own href). */
const DATA_SHOP_SUB_HREFS: readonly string[] = ["/tu-khoa", "/quang-cao", "/don-hang", "/luong-san-pham"];

interface RailEntry {
  readonly key: AppDestinationIcon;
  readonly label: string;
  /** The entry's route per platform; `null` leaves the entry off that platform's rail. */
  readonly href: Readonly<Record<NavPlatform, string | null>>;
  readonly alsoActive?: Partial<Readonly<Record<NavPlatform, readonly string[]>>>;
  /** W3 U-4: the ADR-108 route a TikTok shop keeps behind the `tiktokLegacyScreens` switch. */
  readonly legacyTiktok?: string;
}

/** The single rail, in order. */
const RAIL: readonly RailEntry[] = [
  { key: "overview", label: "Tổng quan", href: { tiktok: "/tong-quan", shopee: "/tong-quan" }, legacyTiktok: "/" },
  // P96b: /xep-hang redirects to /phan-tich (its product table); the entry stays lit for an old link.
  {
    key: "analytics",
    label: "Phân tích",
    href: { tiktok: "/phan-tich", shopee: "/phan-tich" },
    alsoActive: { shopee: ["/xep-hang"], tiktok: ["/xep-hang"] },
    legacyTiktok: "/analytics",
  },
  { key: "decisions", label: ACTIONS_DESTINATION_LABEL, href: { tiktok: "/decisions", shopee: "/decisions" } },
  // Fourth on both platforms; shown only where `GET /v1/demo/juli/enabled` says so (see `destinationsFor`).
  { key: "juli", label: "Juli", href: { tiktok: "/juli", shopee: "/juli" } },
  // P100 redesign: Sản phẩm / Từ khóa / Dịch vụ hiển thị / Đơn hàng / Luồng are sub-tabs of one entry.
  {
    key: "data",
    label: "Dữ liệu shop",
    href: { tiktok: null, shopee: "/san-pham" },
    alsoActive: { shopee: DATA_SHOP_SUB_HREFS },
  },
];

function railFor(platform: NavPlatform, withJuli: boolean, legacyTiktok = false): readonly AppDestination[] {
  return RAIL.flatMap((entry) => {
    const legacy = legacyTiktok && platform === "tiktok" ? entry.legacyTiktok : undefined;
    const href = legacy ?? entry.href[platform];
    if (href === null || (entry.key === "juli" && !withJuli)) return [];
    const alsoActive = legacy ? undefined : entry.alsoActive?.[platform];
    return [{ key: entry.key, label: entry.label, icon: entry.key, href, locked: false, ...(alsoActive ? { alsoActive } : {}) }];
  });
}

/** A TikTok shop's rail (Juli not on): the shared Tổng quan / Phân tích screens (W3). */
export const SHARED_TIKTOK_DESTINATIONS: readonly AppDestination[] = railFor("tiktok", false);
export const SHARED_TIKTOK_DESTINATIONS_WITH_JULI: readonly AppDestination[] = railFor("tiktok", true);

/** A TikTok shop's ADR-108 rail (Trang chủ `/`, Phân tích `/analytics`), behind `tiktokLegacyScreens` (decision #8). */
export const APP_DESTINATIONS: readonly AppDestination[] = railFor("tiktok", false, true);

/** A Shopee shop's rail (ADR-120 decision 2; its routes are unchanged; Juli not on). */
export const SHOPEE_DESTINATIONS: readonly AppDestination[] = railFor("shopee", false);

/** The same rails with the Juli entry, for a shop where the Juli tab is enabled. */
export const APP_DESTINATIONS_WITH_JULI: readonly AppDestination[] = railFor("tiktok", true, true);
export const SHOPEE_DESTINATIONS_WITH_JULI: readonly AppDestination[] = railFor("shopee", true);

/**
 * P100 S2-C (owner, 2026-11-11): on the reviewer's sample shop ("Dữ liệu mẫu") the rail shows only
 * the screens that work there. The other Shopee pages are hidden (not greyed out, no "sắp có") and a
 * direct link to one goes to Tổng quan (`sampleShopRedirect`). The API refuses their routes on its
 * own (S2-F allowlist) — this list is presentation only.
 */
export const SAMPLE_SHOP_DESTINATION_KEYS: readonly AppDestinationIcon[] = ["overview", "analytics", "decisions", "juli", "data"];

export const SAMPLE_SHOP_HOME_HREF = "/tong-quan";

export const SAMPLE_SHOP_DESTINATIONS: readonly AppDestination[] = SHOPEE_DESTINATIONS.filter((d) =>
  SAMPLE_SHOP_DESTINATION_KEYS.includes(d.key),
);
const SAMPLE_SHOP_DESTINATIONS_WITH_JULI: readonly AppDestination[] = SHOPEE_DESTINATIONS_WITH_JULI.filter((d) =>
  SAMPLE_SHOP_DESTINATION_KEYS.includes(d.key),
);

/** `juliEnabled`: the shop's `/v1/demo/juli/enabled` answer; the Juli entry is shown only when true. */
export function destinationsFor(
  platform: NavPlatform,
  options: { readonly sampleShop?: boolean; readonly juliEnabled?: boolean; readonly tiktokLegacy?: boolean } = {},
): readonly AppDestination[] {
  const juli = options.juliEnabled === true;
  if (platform !== "shopee") {
    if (options.tiktokLegacy) return juli ? APP_DESTINATIONS_WITH_JULI : APP_DESTINATIONS;
    return juli ? SHARED_TIKTOK_DESTINATIONS_WITH_JULI : SHARED_TIKTOK_DESTINATIONS;
  }
  if (options.sampleShop) return juli ? SAMPLE_SHOP_DESTINATIONS_WITH_JULI : SAMPLE_SHOP_DESTINATIONS;
  return juli ? SHOPEE_DESTINATIONS_WITH_JULI : SHOPEE_DESTINATIONS;
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
