import type { NextConfig } from "next";

// Standard next build + next start from apps/landing (mirrors apps/demo).
// Do not use output: "standalone" — see ADR-058 (docs/adr/058-release-packaging-shape.md)
// for the measured reasoning; the same decision covers both public Next apps.
// The service starts node_modules/.bin/next directly from this directory.

/**
 * Renamed URLs (D43.1). 301, not Next's default 308 for `permanent: true`:
 * D43 asks for a 301 and every crawler treats both the same. nginx proxies
 * every path to Next (infra/nginx/app-juli.com.conf), so nothing overrides it.
 * Unknown paths stay 404 — only list real renames here.
 */
export const RENAMED_PATHS: ReadonlyArray<{ source: string; destination: string }> = [
  { source: "/product", destination: "/san-pham" },
];

const YEAR = 60 * 60 * 24 * 365;
const WEEK = 60 * 60 * 24 * 7;

/**
 * Browser cache lifetimes for files in `public/` (PageSpeed "efficient cache
 * lifetimes", D43.5). `/_next/static/*` is content-hashed and already sent
 * `public, max-age=31536000, immutable` by Next itself.
 * - `/media/*` names are versioned (`-v1`, scripts/media.py): immutable.
 * - `/og/*`, `/videos/*` and the icons keep stable names: one week, then revalidate.
 */
export const STATIC_CACHE_HEADERS = [
  { source: "/media/:path*", value: `public, max-age=${YEAR}, immutable` },
  { source: "/og/:path*", value: `public, max-age=${WEEK}, stale-while-revalidate=${WEEK}` },
  { source: "/videos/:path*", value: `public, max-age=${WEEK}, stale-while-revalidate=${WEEK}` },
] as const;

const nextConfig: NextConfig = {
  transpilePackages: ["@juli/ui", "@juli/brand", "@juli/tiktok-events"],
  experimental: {
    // The whole stylesheet is ~10 KB gzipped: inlining it removes the one
    // render-blocking request in front of the first paint (PageSpeed
    // "render-blocking requests", LCP render delay; D43.5).
    inlineCss: true,
  },
  async redirects() {
    return RENAMED_PATHS.map(({ source, destination }) => ({ source, destination, statusCode: 301 }));
  },
  async headers() {
    return STATIC_CACHE_HEADERS.map(({ source, value }) => ({
      source,
      headers: [{ key: "Cache-Control", value }],
    }));
  },
};

export default nextConfig;
