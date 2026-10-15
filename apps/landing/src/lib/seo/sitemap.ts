import type { MetadataRoute } from "next";

import { absoluteUrl } from "./config";
import type { SiteRoute } from "./routes";

/**
 * Sitemap entries for `routes`, skipping `noindex` ones — a blog draft awaiting
 * owner approval is rendered but never submitted to search (P33-D).
 */
export function sitemapEntries(routes: readonly SiteRoute[]): MetadataRoute.Sitemap {
  return routes
    .filter((route) => !route.noindex)
    .map((route) => ({
      url: absoluteUrl(route.path),
      lastModified: route.lastModified,
      ...(route.changeFrequency ? { changeFrequency: route.changeFrequency } : {}),
      ...(route.priority !== undefined ? { priority: route.priority } : {}),
    }));
}
