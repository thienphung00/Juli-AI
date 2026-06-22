import type { Metadata, Viewport } from "next";
import Script from "next/script";
import { AuthProvider } from "@/lib/auth-context";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { ModeProvider } from "@/lib/mode-context";
import { WORKSPACE_THEME_INIT_SCRIPT } from "@/lib/theme-init";
import "./globals.css";

export const metadata: Metadata = {
  title: "Juli - Quản lý TikTok Shop",
  description: "Hệ thống quản lý TikTok Shop thông minh",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#fef5f6",
  colorScheme: "dark light",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi" suppressHydrationWarning className="font-sans">
      <head>
        <Script id="workspace-theme-init" strategy="beforeInteractive">
          {WORKSPACE_THEME_INIT_SCRIPT}
        </Script>
      </head>
      <body
        className="min-h-screen antialiased"
        style={{ background: "var(--background)", color: "var(--foreground)" }}
      >
        <AuthProvider>
          <ModeProvider>
            <DemoPersonaProvider>{children}</DemoPersonaProvider>
          </ModeProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
