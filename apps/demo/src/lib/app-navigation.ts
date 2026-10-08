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

export type AppDestinationIcon = "home" | "decisions" | "analytics" | "juli";

export interface AppDestination {
  readonly key: AppDestinationIcon;
  readonly label: string;
  readonly icon: AppDestinationIcon;
  /** `null` for a locked destination — there is no page to navigate to. */
  readonly href: string | null;
  readonly locked: boolean;
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
