import type { MetadataRoute } from "next";

import type { OgImage } from "../config";

/**
 * One public page of app-juli.com. The registry is the single source for the
 * page's <title>, description, canonical, Open Graph, breadcrumb trail and its
 * sitemap entry — a page that is not registered cannot call `buildMetadata`.
 */
export interface SiteRoute {
  /** Site path, leading slash, no trailing slash (`/` for home). Vietnamese slugs. */
  path: string;
  /** Full <title>: "<Benefit> | Juli AI", ≤ 60 characters, unique. */
  title: string;
  /** Meta description, ≤ 155 characters, unique. */
  description: string;
  /** Last meaningful content change, `YYYY-MM-DD` (sitemap `lastmod`). Bump it when you edit the page. */
  lastModified: string;
  /** Short label for the BreadcrumbList (`Sản phẩm`, `Phân tích shop`). */
  breadcrumbName: string;
  /** Parent path for the breadcrumb trail; defaults to `/`. */
  parent?: string;
  changeFrequency?: NonNullable<MetadataRoute.Sitemap[number]["changeFrequency"]>;
  /** Sitemap priority 0–1. */
  priority?: number;
  /** Page-specific 1200×630 social image; defaults to the branded card. */
  ogImage?: OgImage;
  /** `article` for blog posts (adds published/modified times to OG). */
  ogType?: "website" | "article";
}
