import type { Metadata } from "next";
import type { ReactNode } from "react";

import { DemoShell } from "../components/demo-shell";
import { TikTokTracking } from "../components/tiktok-tracking";
import "./globals.css";

export const metadata: Metadata = {
  title: "Juli Demo",
  description: "Trải nghiệm cách Juli giúp bạn hiểu shop và đưa ra quyết định.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="vi">
      <body>
        {/* Loads the TikTok pixel only for a visitor who arrived from an ad —
            see the component for why the Demo gates what Landing does not. */}
        <TikTokTracking />
        <DemoShell>{children}</DemoShell>
      </body>
    </html>
  );
}
