import type { NextConfig } from "next";

// Standard next build + next start from apps/landing (mirrors apps/demo).
// Do not use output: "standalone" — see ADR-058 (docs/adr/058-release-packaging-shape.md)
// for the measured reasoning; the same decision covers both public Next apps.
// The service starts node_modules/.bin/next directly from this directory.
const nextConfig: NextConfig = {
  transpilePackages: ["@juli/ui", "@juli/brand"],
};

export default nextConfig;
