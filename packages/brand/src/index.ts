export { JuliLogo } from "./juli-logo";
export type { JuliLogoProps, JuliLogoVariant } from "./juli-logo";

/**
 * Canonical brand asset filenames under `@juli/brand/assets/` (ADR-056).
 * Import via the package export, e.g.
 * `import hero from "@juli/brand/assets/hero-mascot.webp";`
 * Filenames are stable — a quality upgrade replaces the file in place with no
 * code change.
 */
export const BRAND_ASSETS = {
  logoWordmark: "logo-wordmark.png",
  birdGlyph: "bird-glyph.png",
  heroMascot: "hero-mascot.webp",
} as const;
