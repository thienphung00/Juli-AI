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
      <div className="mx-auto flex max-w-lg items-center justify-around px-1 pt-2 pb-3">
        {BOTTOM_NAV_TABS.map(({ href, label, Icon, color, live }) => {
          const isActive = isNavTabActive(pathname, href);
          const isJuli = href === "/ai-chat";

          return (
            <Link
              key={href}
              href={href}
              className="relative flex flex-col items-center gap-1 rounded-xl px-2 py-1 transition-all"
              aria-current={isActive ? "page" : undefined}
            >
              {isActive && !isJuli && (
                <span
                  className="absolute inset-0 rounded-xl"
                  style={{ background: `${color}18` }}
                />
              )}

              {isJuli ? (
                <span className="relative">
                  <span
                    className="flex h-10 w-10 items-center justify-center rounded-2xl transition-all"
                    style={
                      isActive
                        ? {
                            background: "linear-gradient(135deg, #FF1493 0%, #FF69B4 100%)",
                            boxShadow: "0 4px 14px #FF149340",
                          }
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
                    style={{ color: isActive ? color : "var(--muted-foreground)" }}
                  />
                  {live && (
                    <span
                      className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border animate-pulse-slow"
                      style={{ background: "#E61282", borderColor: "var(--background)" }}
                    />
                  )}
                </span>
              )}

              <span
                className="text-[9px] font-semibold transition-colors"
                style={{ color: isActive && !isJuli ? color : "var(--muted-foreground)" }}
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
