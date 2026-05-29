import type { LucideIcon } from "lucide-react";
import { Home, Radio, TrendingUp, BarChart2, Sparkles } from "lucide-react";

export interface NavTab {
  href: string;
  label: string;
  Icon: LucideIcon;
  color: string;
  live?: boolean;
}

/** Bottom navigation — exactly 5 tabs (issue #77). */
export const BOTTOM_NAV_TABS: NavTab[] = [
  { href: "/", label: "Trang chủ", Icon: Home, color: "#FF1493" },
  { href: "/livestreams", label: "Trực tiếp", Icon: Radio, color: "#E61282", live: true },
  { href: "/trends", label: "Xu hướng", Icon: TrendingUp, color: "#FF69B4" },
  { href: "/operation", label: "Vận hành", Icon: BarChart2, color: "#FF69B4" },
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
