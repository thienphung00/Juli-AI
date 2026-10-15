import type { MetadataRoute } from "next";

/**
 * Crawling is ALLOWED on purpose (D43.5, AC-33.3): the demo and ops hosts are
 * kept out of the index by `noindex` (X-Robots-Tag + meta), and a crawler can
 * only see a noindex on a page it is allowed to fetch. A `Disallow: /` here
 * would leave already-known URLs indexed. No sitemap: nothing here should rank.
 */
export default function robots(): MetadataRoute.Robots {
  return { rules: { userAgent: "*", allow: "/" } };
}
