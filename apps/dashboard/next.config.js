const { LEGACY_ROUTE_REDIRECTS } = require("./legacy-redirects.js");

const path = require("path");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  turbopack: {
    root: path.join(__dirname),
  },
  experimental: {
    optimizePackageImports: ["lucide-react"],
  },
  async redirects() {
    return [...LEGACY_ROUTE_REDIRECTS];
  },
};

module.exports = nextConfig;
