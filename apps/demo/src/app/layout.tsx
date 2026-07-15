import type { Metadata } from "next";
import type { ReactNode } from "react";

import { DemoShell } from "../components/demo-shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Juli Demo",
  description: "Trải nghiệm cách Juli giúp bạn hiểu shop và đưa ra quyết định.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="vi">
      <body>
        <DemoShell>{children}</DemoShell>
      </body>
    </html>
  );
}
