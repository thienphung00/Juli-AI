"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BOTTOM_NAV_TABS, isNavTabActive } from "@/lib/nav-config";

export function NavBar() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Điều hướng chính"
      className="fixed bottom-0 left-0 right-0 z-50 safe-area-bottom"
      style={{ background: "var(--card)", borderTop: "1px solid var(--border)" }}
    >
      <div className="app-container flex items-center justify-around !px-1 pt-2 pb-3">
        {BOTTOM_NAV_TABS.map(({ href, label, Icon, live }) => {
          const isActive = isNavTabActive(pathname, href);
          const isJuli = href === "/ai-chat";
          const activeColor = "var(--primary)";

          return (
            <Link
              key={href}
              href={href}
              className="relative flex min-h-[44px] min-w-[44px] flex-col items-center justify-center gap-1 rounded-xl px-3 py-1 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
              aria-current={isActive ? "page" : undefined}
            >
              {isActive && (
                <span
                  className="absolute inset-0 rounded-xl"
                  style={{ background: "color-mix(in srgb, var(--primary) 12%, transparent)" }}
                />
              )}

              {isJuli ? (
                <span className="relative">
                  <span
                    className={`flex h-10 w-10 items-center justify-center rounded-2xl transition-all${isActive ? " gradient-primary" : ""}`}
                    style={
                      isActive
                        ? { boxShadow: "0 4px 14px var(--brand-glow)" }
                        : { background: "var(--muted)", border: "1px solid var(--border)" }
                    }
                  >
                    <Icon
                      size={20}
                      color={isActive ? "#fff" : "var(--muted-foreground)"}
                    />
                  </span>
                  <span
                    className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 animate-pulse-slow"
                    style={{ background: "var(--primary)", borderColor: "var(--background)" }}
                  />
                </span>
              ) : (
                <span className="relative flex h-7 w-7 items-center justify-center">
                  <Icon
                    size={22}
                    style={{ color: isActive ? activeColor : "var(--muted-foreground)" }}
                  />
                  {live && (
                    <span
                      className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border animate-pulse-slow"
                      style={{ background: "var(--primary)", borderColor: "var(--background)" }}
                    />
                  )}
                </span>
              )}

              <span
                className="text-[11px] font-semibold transition-colors"
                style={{ color: isActive ? activeColor : "var(--muted-foreground)" }}
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
