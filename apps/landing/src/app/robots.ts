import type { MetadataRoute } from "next";

import { SITE_URL } from "../lib/seo";

/** Every public page is crawlable; only the Events API relay is not a page. */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/", disallow: "/api/" },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
