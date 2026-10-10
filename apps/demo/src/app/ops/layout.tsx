import type { Metadata } from "next";
import type { ReactNode } from "react";

/** Juli Ops (P16, D25): internal, never indexed; served on ops.app-juli.com only (middleware). */
export const metadata: Metadata = {
  title: "Juli Ops",
  robots: { index: false, follow: false, nocache: true, googleBot: { index: false, follow: false } },
};

export default function OpsLayout({ children }: { children: ReactNode }) {
  return children;
}
