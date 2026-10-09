/**
 * The Demo CTA destination: the public Demo in Mock mode (no signup needed).
 * Overridable per environment for preview deployments.
 */
export const DEMO_URL =
  process.env.NEXT_PUBLIC_DEMO_URL ?? "https://demo.app-juli.com/";

/**
 * The single Login/Signup destination for the landing CTAs (hero + closing
 * trial CTA). It points at the Demo, which carries its own Login/Signup entry,
 * because the main-domain `/login` route does not exist yet (Phase 3.5-C owns
 * it, ADR-048 / ADR-050). Overridable per environment.
 */
export const LOGIN_URL =
  process.env.NEXT_PUBLIC_LOGIN_URL ?? "https://demo.app-juli.com/";

/** In-page anchors used by header nav and secondary CTAs. */
export const SECTION_IDS = {
  features: "tinh-nang",
  comparison: "giai-phap",
  contact: "lien-he",
} as const;

/**
 * The origins this site is actually served from, and the only ones whose
 * pages may post to `/api/tt/event`.
 *
 * Apex only for production: nginx 301s `www.app-juli.com` to `app-juli.com`
 * (infra/nginx/app-juli.com.conf), so no page is ever served from www and no
 * browser will send it as an Origin. The dev entry is the port
 * `package.json` binds `next dev` and `next start` to.
 */
export const SITE_ORIGINS: readonly string[] = [
  "https://app-juli.com",
  "http://localhost:3007",
];
