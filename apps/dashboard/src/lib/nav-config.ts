import type { LucideIcon } from "lucide-react";
import { Home, ListChecks, Sparkles } from "lucide-react";

export interface NavTab {
  href: string;
  label: string;
  Icon: LucideIcon;
  color: string;
  live?: boolean;
}

/** Bottom navigation — Home, Decisions, Juli AI (ADR-014 #191). */
export const BOTTOM_NAV_TABS: NavTab[] = [
  { href: "/", label: "Trang chủ", Icon: Home, color: "var(--primary)" },
  { href: "/decisions", label: "Quyết định", Icon: ListChecks, color: "var(--primary)" },
  { href: "/ai-chat", label: "Juli", Icon: Sparkles, color: "var(--primary)" },
];

import { LEGACY_ROUTE_REDIRECTS as legacyRedirects } from "../../legacy-redirects.js";

export const LEGACY_ROUTE_REDIRECTS = legacyRedirects as readonly {
  source: string;
  destination: string;
  permanent: boolean;
}[];

export function isNavTabActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
