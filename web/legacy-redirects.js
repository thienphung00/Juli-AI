/** Shared with next.config.js and src/lib/nav-config.ts (issue #77). */
const LEGACY_ROUTE_REDIRECTS = [
  { source: "/alerts", destination: "/", permanent: true },
  { source: "/recommendations", destination: "/", permanent: true },
  { source: "/products", destination: "/trends", permanent: true },
  { source: "/orders", destination: "/operation", permanent: true },
  { source: "/inventory", destination: "/operation", permanent: true },
  { source: "/creators", destination: "/operation", permanent: true },
];

module.exports = { LEGACY_ROUTE_REDIRECTS };
