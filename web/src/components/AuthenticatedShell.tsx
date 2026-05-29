"use client";

import type { ReactNode } from "react";
import { NavBar } from "./NavBar";
import { PageHeader } from "./PageHeader";

interface AuthenticatedShellProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
}

export function AuthenticatedShell({ title, subtitle, children }: AuthenticatedShellProps) {
  return (
    <div className="min-h-screen pb-24" style={{ background: "var(--background)" }}>
      <PageHeader title={title} subtitle={subtitle} />
      <main className="mx-auto max-w-lg px-4 pt-4">{children}</main>
      <NavBar />
    </div>
  );
}
