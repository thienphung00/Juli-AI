const { LEGACY_ROUTE_REDIRECTS } = require("./legacy-redirects.js");

const path = require("path");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  turbopack: {
    // Must be the repo root, not this app directory. With `root: __dirname`,
    // `next dev` starts but every Turbopack build fails:
    //
    //   Error: Next.js inferred your workspace root, but it may not be correct.
    //   We couldn't find the Next.js package (next/package.json) from the project
    //   directory: apps/dashboard/src/app
    //
    // even though apps/dashboard/node_modules/next is present. Verified empirically
    // on Next 16.2.11: __dirname -> Turbopack build error, repo root -> HTTP 200.
    // Note this app is npm-owned and excluded from the pnpm workspace (see
    // pnpm-workspace.yaml), so the repo root is not a pnpm workspace root for it —
    // Turbopack simply needs the wider root to resolve from.
    root: path.join(__dirname, "..", ".."),
  },
  experimental: {
    optimizePackageImports: ["lucide-react"],
  },
  async redirects() {
    return [...LEGACY_ROUTE_REDIRECTS];
  },
};

module.exports = nextConfig;
