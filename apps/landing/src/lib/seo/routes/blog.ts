import type { SiteRoute } from "./types";

/**
 * `/blog` index and posts (D43.7). Owner: P33-D — posts use `ogType: "article"`
 * and `parent: "/blog"`; render `articleSchema()` on the post page.
 */
export const BLOG_ROUTES: readonly SiteRoute[] = [];
