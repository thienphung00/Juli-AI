import type { Metadata } from "next";
import type { ReactNode } from "react";

import { CookieConsent } from "../components/cookie-consent";
import { JsonLd, organizationSchema, ROOT_METADATA, websiteSchema } from "../lib/seo";

import { beVietnamPro } from "./fonts";
import "./globals.css";
import "../components/ui/ui.css";

/** Site defaults (metadataBase); each page sets its own via `buildMetadata`. */
export const metadata: Metadata = ROOT_METADATA;

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html className={beVietnamPro.variable} lang="vi">
      <body>
        {/* Organization + WebSite on every page (D43.5). */}
        <JsonLd data={[organizationSchema(), websiteSchema()]} />
        {children}
        <CookieConsent />
      </body>
    </html>
  );
}
