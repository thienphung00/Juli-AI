"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Home, Radio, TrendingUp, BarChart2, Sparkles } from "lucide-react";

const navItems = [
  { href: "/",            label: "Trang chủ", Icon: Home,        color: "#FF1493" },
  { href: "/livestreams", label: "Trực tiếp", Icon: Radio,       color: "#E61282", live: true },
  { href: "/products",    label: "Xu hướng",  Icon: TrendingUp,  color: "#FF69B4" },
  { href: "/orders",      label: "Vận hành",  Icon: BarChart2,   color: "#FF85C2" },
  { href: "/creators",    label: "Creators",  Icon: Sparkles,    color: "#FF1493", ai: true },
];

export function NavBar() {
  const pathname = usePathname();

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-50 safe-area-bottom"
      style={{ background: "var(--card)", borderTop: "1px solid var(--border)" }}
    >
      <div className="mx-auto flex max-w-lg items-center justify-around px-1 pt-2 pb-3">
        {navItems.map(({ href, label, Icon, color, live, ai }) => {
          const isActive = pathname === href;

          return (
            <Link
              key={href}
              href={href}
              className="relative flex flex-col items-center gap-1 rounded-xl px-3 py-1 transition-all"
            >
              {/* Active background pill */}
              {isActive && !ai && (
                <span
                  className="absolute inset-0 rounded-xl"
                  style={{ background: `${color}18` }}
                />
              )}

              {/* AI / Sparkles special button */}
              {ai ? (
                <span className="relative">
                  <span
                    className="flex h-10 w-10 items-center justify-center rounded-2xl transition-all"
                    style={
                      isActive
                        ? { background: "linear-gradient(135deg, #FF1493 0%, #FF69B4 100%)", boxShadow: "0 4px 14px #FF149340" }
                        : { background: "var(--muted)", border: "1px solid var(--border)" }
                    }
                  >
                    <Icon size={20} color={isActive ? "#fff" : "var(--muted-foreground)"} />
                  </span>
                  {/* Pulse dot */}
                  <span
                    className="absolute -top-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 animate-pulse-slow"
                    style={{ background: "var(--primary)", borderColor: "var(--background)" }}
                  />
                </span>
              ) : (
                <span className="relative flex h-7 w-7 items-center justify-center">
                  <Icon
                    size={22}
                    style={{ color: isActive ? color : "var(--muted-foreground)" }}
                  />
                  {/* Live dot on livestream tab */}
                  {live && (
                    <span
                      className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full border animate-pulse-slow"
                      style={{ background: "#E61282", borderColor: "var(--background)" }}
                    />
                  )}
                </span>
              )}

              <span
                className="text-[9px] font-semibold transition-colors"
                style={{ color: isActive && !ai ? color : "var(--muted-foreground)" }}
              >
                {label}
              </span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
