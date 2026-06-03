import type { LucideIcon } from "lucide-react";
import { Home, Users, Lightbulb, Sparkles } from "lucide-react";

export interface NavTab {
  href: string;
  label: string;
  Icon: LucideIcon;
  color: string;
  live?: boolean;
}

/** Bottom navigation — recommendation-first (issue #95). */
export const BOTTOM_NAV_TABS: NavTab[] = [
  { href: "/", label: "Trang chủ", Icon: Home, color: "#FF1493" },
  { href: "/creators", label: "Creators", Icon: Users, color: "#FF69B4" },
  { href: "/recommendations", label: "Gợi ý", Icon: Lightbulb, color: "#E61282" },
  { href: "/ai-chat", label: "Juli", Icon: Sparkles, color: "#FF1493" },
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
