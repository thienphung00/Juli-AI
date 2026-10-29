import type { Metadata } from "next";
import { Be_Vietnam_Pro } from "next/font/google";
import type { ReactNode } from "react";

import { DemoShell } from "../components/demo-shell";
import { TikTokTracking } from "../components/tiktok-tracking";
import "./globals.css";
import "./quyet-dinh.css";
import "./phan-tich.css";
import "./auth-screen.css";

/** Quyết định's typeface (AC-10.3 artboards) and the auth screen's (P34-F,
 *  D44.1); exposed as a variable so only those screens use it — the shell
 *  keeps Inter. */
const beVietnamPro = Be_Vietnam_Pro({
  subsets: ["latin", "vietnamese"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
  // Same fallback chain as the artboards ('Be Vietnam Pro', system-ui,
  // sans-serif): glyphs outside the font's subsets (→, ▲) come from the
  // system face, not an Arial-metric shim.
  fallback: ["system-ui", "sans-serif"],
  adjustFontFallback: false,
  variable: "--font-be-vietnam-pro",
});

export const metadata: Metadata = {
  title: "Juli",
  description: "Trải nghiệm cách Juli giúp bạn hiểu shop và đưa ra quyết định.",
  // Never indexed (D43.5): <meta name="robots" content="noindex, nofollow">,
  // alongside the X-Robots-Tag header (next.config.ts + middleware).
  robots: { index: false, follow: false, googleBot: { index: false, follow: false } },
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html className={beVietnamPro.variable} lang="vi">
      <body>
        {/* Loads the TikTok pixel only for a visitor who arrived from an ad —
            see the component for why the Demo gates what Landing does not. */}
        <TikTokTracking />
        <DemoShell>{children}</DemoShell>
      </body>
    </html>
  );
}
