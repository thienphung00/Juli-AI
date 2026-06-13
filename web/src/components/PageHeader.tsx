"use client";

import type { ShopMetadata } from "@/lib/mock-data/operations/schemas";

import { ModeSwitcher } from "./ModeSwitcher";
import { AlertBell } from "./AlertBell";
import { ShopInfoHeader } from "./workflows/operations/ShopInfoHeader";

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  shopMetadata?: ShopMetadata;
}

export function PageHeader({ title, subtitle, shopMetadata }: PageHeaderProps) {
  return (
    <header
      role="banner"
      className="app-header sticky top-0 z-10 px-4 py-3"
      style={{ background: "var(--background)", borderBottom: "1px solid var(--border)" }}
    >
      <div className="app-container flex items-start justify-between gap-3 !px-0">
        <div className="min-w-0 flex-1">
          <h1
            className="text-lg font-bold leading-snug"
            style={{ color: "var(--foreground)" }}
          >
            {title}
          </h1>
          {shopMetadata ? (
            <ShopInfoHeader metadata={shopMetadata} />
          ) : subtitle ? (
            <p
              className="mt-0.5 line-clamp-2 text-xs"
              style={{ color: "var(--muted-foreground)" }}
            >
              {subtitle}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <ModeSwitcher />
          <AlertBell />
        </div>
      </div>
    </header>
  );
}
