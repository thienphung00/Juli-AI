/**
 * The one CTA destination — the public Demo in Mock mode (no signup needed).
 * Overridable per environment for preview deployments.
 */
export const DEMO_URL =
  process.env.NEXT_PUBLIC_DEMO_URL ?? "https://demo.app-juli.com/";

/** In-page anchors used by header nav and secondary CTAs. */
export const SECTION_IDS = {
  features: "tinh-nang",
  comparison: "giai-phap",
  contact: "lien-he",
} as const;
