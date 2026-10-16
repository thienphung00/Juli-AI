import { BLOG_ROUTES } from "./blog";
import { CAPABILITY_ROUTES } from "./capabilities";
import { CORE_ROUTES } from "./core";
import { PRODUCT_ROUTES } from "./product";
import { SIGNUP_ROUTES } from "./signup";
import { TOOL_ROUTES } from "./tools";
import type { SiteRoute } from "./types";

export type { SiteRoute } from "./types";

/**
 * Every indexable page, in sitemap order. Split by owner (core / product /
 * capabilities / tools / blog / signup) so parallel agents append to different files.
 */
export const SITE_ROUTES: readonly SiteRoute[] = [
  ...CORE_ROUTES,
  ...PRODUCT_ROUTES,
  ...CAPABILITY_ROUTES,
  ...TOOL_ROUTES,
  ...BLOG_ROUTES,
  ...SIGNUP_ROUTES,
];

const BY_PATH = new Map(SITE_ROUTES.map((route) => [route.path, route]));

/** The registered route for `path`; throws so an unregistered page fails the build. */
export function getRoute(path: string): SiteRoute {
  const route = BY_PATH.get(path);
  if (!route) {
    throw new Error(`SEO: "${path}" is not in the route registry (src/lib/seo/routes/).`);
  }
  return route;
}

export function hasRoute(path: string): boolean {
  return BY_PATH.has(path);
}

export interface BreadcrumbItem {
  name: string;
  path: string;
}

/** Home → … → the page, following `parent` links (home alone for `/`). */
export function breadcrumbTrail(path: string): BreadcrumbItem[] {
  const trail: BreadcrumbItem[] = [];
  const seen = new Set<string>();
  let current: SiteRoute | undefined = getRoute(path);
  while (current) {
    if (seen.has(current.path)) {
      throw new Error(`SEO: breadcrumb cycle at "${current.path}"`);
    }
    seen.add(current.path);
    trail.unshift({ name: current.breadcrumbName, path: current.path });
    if (current.path === "/") break;
    current = getRoute(current.parent ?? "/");
  }
  return trail;
}
