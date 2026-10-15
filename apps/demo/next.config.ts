import type { NextConfig } from "next";

// Standard next build + next start from apps/demo (matches juli-web / App Review).
// Do not use output: "standalone" — see ADR-058 (docs/adr/058-release-packaging-shape.md)
// for the measured reasoning. In short: the #835 spike proved the pnpm symlink tree
// resolves through a release-slot indirection, so the risk that would have forced
// self-contained output did not materialise, and standalone's entrypoint path is derived
// from the inferred workspace root rather than fixed.
// juli-demo.service starts node_modules/.bin/next directly from this directory.
/**
 * demo.app-juli.com and ops.app-juli.com are never indexed (D43.5, AC-33.3).
 * Every path — pages, static files, API routes — carries the header; the
 * middleware sets it too on the responses it builds itself (404s, redirects).
 * robots.txt stays crawlable (src/app/robots.ts) so Google can see the noindex.
 */
export const NOINDEX_HEADERS = [
  { source: "/:path*", headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }] },
];

const nextConfig: NextConfig = {
  transpilePackages: ["@juli/ui", "@juli/utils", "@juli/tiktok-events"],
  async headers() {
    return NOINDEX_HEADERS;
  },
  // The per-metric KPI dashboard (/analytics/<metricKey>) was retired; /analytics
  // is the Phân tích page (ADR-109). Old bookmarks land there instead of 404ing.
  async redirects() {
    return [{ source: "/analytics/:path+", destination: "/analytics", permanent: true }];
  },
};

export default nextConfig;
