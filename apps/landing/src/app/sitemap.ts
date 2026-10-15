import type { MetadataRoute } from "next";

import { absoluteUrl, SITE_ROUTES } from "../lib/seo";

/** Every registered page with its `lastmod` (D43.5). Add pages in src/lib/seo/routes/. */
export default function sitemap(): MetadataRoute.Sitemap {
  return SITE_ROUTES.map((route) => ({
    url: absoluteUrl(route.path),
    lastModified: route.lastModified,
    ...(route.changeFrequency ? { changeFrequency: route.changeFrequency } : {}),
    ...(route.priority !== undefined ? { priority: route.priority } : {}),
  }));
}
