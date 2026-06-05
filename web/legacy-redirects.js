/** Shared with next.config.js and src/lib/nav-config.ts (issue #77). */
const LEGACY_ROUTE_REDIRECTS = [
  { source: "/creators", destination: "/", permanent: true },
  { source: "/recommendations", destination: "/", permanent: true },
  { source: "/alerts", destination: "/", permanent: true },
  { source: "/products", destination: "/trends", permanent: true },
  { source: "/orders", destination: "/operation", permanent: true },
  { source: "/inventory", destination: "/operation", permanent: true },
  { source: "/livestreams", destination: "/", permanent: true },
  { source: "/trends", destination: "/", permanent: true },
  { source: "/operation", destination: "/", permanent: true },
];

module.exports = { LEGACY_ROUTE_REDIRECTS };
