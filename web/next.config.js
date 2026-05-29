const { LEGACY_ROUTE_REDIRECTS } = require("./legacy-redirects.js");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    optimizePackageImports: ["lucide-react"],
  },
  async redirects() {
    return [...LEGACY_ROUTE_REDIRECTS];
  },
};

module.exports = nextConfig;
