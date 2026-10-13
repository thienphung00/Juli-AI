import type { MetadataRoute } from "next";

import { SITE_PAGES } from "../lib/site";

const ORIGIN = "https://app-juli.com";

export default function sitemap(): MetadataRoute.Sitemap {
  const paths = ["/", ...SITE_PAGES.map((page) => page.href), "/privacy", "/terms"];
  return paths.map((path) => ({ url: `${ORIGIN}${path}` }));
}
