"use client";

import type { ReactNode } from "react";
import { useWorkspaceModeOptional } from "@/lib/mode-context";
import { AffiliateOutOfScope } from "./AffiliateOutOfScope";
import { NavBar } from "./NavBar";
import { PageHeader } from "./PageHeader";

interface AuthenticatedShellProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
  /** Pin chat input above bottom nav on AI chat route */
  stickyFooter?: ReactNode;
}

export function AuthenticatedShell({
  title,
  subtitle,
  children,
  stickyFooter,
}: AuthenticatedShellProps) {
  const modeContext = useWorkspaceModeOptional();
  const isAffiliateOutOfScope = modeContext?.mode === "affiliate";

  return (
    <div className="min-h-screen pb-24" style={{ background: "var(--background)" }}>
      <PageHeader title={title} subtitle={subtitle} />
      <main className="app-container pt-4">
        {isAffiliateOutOfScope ? <AffiliateOutOfScope /> : children}
      </main>
      {stickyFooter && !isAffiliateOutOfScope && (
        <div
          className="fixed inset-x-0 bottom-[4.5rem] z-40 border-t px-4 py-3 safe-area-bottom"
          style={{
            background: "var(--background)",
            borderColor: "var(--border)",
          }}
          data-testid="sticky-chat-footer"
        >
          <div className="app-container !px-0">{stickyFooter}</div>
        </div>
      )}
      <NavBar />
    </div>
  );
}
