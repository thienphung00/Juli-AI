import type { MetadataRoute } from "next";

/** Every public page is crawlable; only the Events API relay is not a page. */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/", disallow: "/api/" },
    sitemap: "https://app-juli.com/sitemap.xml",
  };
}
