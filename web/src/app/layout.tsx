import type { Metadata, Viewport } from "next";
import { AuthProvider } from "@/lib/auth-context";
import "./globals.css";

export const metadata: Metadata = {
  title: "Juli - Quản lý TikTok Shop",
  description: "Hệ thống quản lý TikTok Shop thông minh",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#0a0a0a",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi" className="dark">
      <head>
        {/* viewport + themeColor handled by `export const viewport` */}
      </head>
      <body className="min-h-screen antialiased" style={{ background: "var(--background)", color: "var(--foreground)" }}>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
