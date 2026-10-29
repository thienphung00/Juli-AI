/**
 * The origins the Demo is served from, and the only ones whose pages may post
 * to `/api/tt/event`. The dev entry is the port `package.json` binds
 * `next dev` to; production is the two hostnames one vhost serves
 * (infra/nginx/demo.app-juli.com.conf).
 */
export const SITE_ORIGINS: readonly string[] = [
  "https://demo.app-juli.com",
  "https://app.app-juli.com",
  "http://localhost:3100",
];
