import type { MetadataRoute } from "next";

import { SITE_ROUTES, sitemapEntries } from "../lib/seo";

/**
 * Every indexable registered page with its `lastmod` (D43.5). Add pages in
 * src/lib/seo/routes/; `noindex` routes (blog drafts) are left out.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  return sitemapEntries(SITE_ROUTES);
}
