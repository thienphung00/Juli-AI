"use client";

import { ModeSwitcher } from "./ModeSwitcher";
import { AlertBell } from "./AlertBell";

interface PageHeaderProps {
  title: string;
  subtitle?: string;
}

export function PageHeader({ title, subtitle }: PageHeaderProps) {
  return (
    <header
      role="banner"
      className="app-header sticky top-0 z-10 px-4 py-3"
      style={{ background: "var(--background)", borderBottom: "1px solid var(--border)" }}
    >
      <div className="mx-auto flex max-w-lg items-center justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h1
            className="truncate text-lg font-bold"
            style={{ color: "var(--foreground)" }}
          >
            {title}
          </h1>
          {subtitle && (
            <p className="mt-0.5 truncate text-xs" style={{ color: "var(--muted-foreground)" }}>
              {subtitle}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <ModeSwitcher />
          <AlertBell />
        </div>
      </div>
    </header>
  );
}
