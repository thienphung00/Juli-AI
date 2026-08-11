/**
 * The Demo CTA destination: the public Demo in Mock mode (no signup needed).
 * Overridable per environment for preview deployments.
 */
export const DEMO_URL =
  process.env.NEXT_PUBLIC_DEMO_URL ?? "https://demo.app-juli.com/";

/**
 * The single Login/Signup destination, shared by this landing page and the
 * Demo's own Login/Signup entry so the two can never drift apart. Sellers
 * connect their shop via TikTok OAuth here, and Juli returns the three
 * improvements it found in their data.
 *
 * Auth lives on the main domain (`app-juli.com`), which is what `apps/landing`
 * serves — not on the Demo subdomain. The Demo's own Login/Signup entry points
 * here too, so the two can never drift apart.
 *
 * NOTE: `/login` does not exist yet — Phase 3.5-C owns it (ADR-048 / ADR-050), and
 * the route returns 404 today. Until it ships, either set NEXT_PUBLIC_LOGIN_URL to
 * a destination that resolves, or hold the production deploy of the paired hero CTA.
 * Never ship this pointing at a 404.
 */
export const LOGIN_URL =
  process.env.NEXT_PUBLIC_LOGIN_URL ?? "https://app-juli.com/login";

/** In-page anchors used by header nav and secondary CTAs. */
export const SECTION_IDS = {
  features: "tinh-nang",
  comparison: "giai-phap",
  contact: "lien-he",
} as const;
