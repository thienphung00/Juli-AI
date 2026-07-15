"use client";

import { PrimaryNavigation } from "@juli/ui";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { demoDestinations } from "../lib/mock-data";

export function DemoShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="demo-shell">
      <header className="demo-header">
        <Link className="demo-wordmark" href="/" aria-label="Juli — Trang chủ">
          Juli
        </Link>
        <span className="demo-badge">Dữ liệu mẫu</span>
      </header>
      <PrimaryNavigation
        activePath={pathname}
        destinations={demoDestinations}
        label="Điều hướng chính"
      />
      <main className="demo-main">{children}</main>
    </div>
  );
}
