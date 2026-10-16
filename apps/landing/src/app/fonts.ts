import localFont from "next/font/local";

/**
 * Be Vietnam Pro (D44.1), self-hosted: 400/500/600, each one woff2 holding
 * the Latin + Vietnamese subsets (Google Fonts' unicode ranges, subset with
 * fonttools from the upstream OFL TTFs — ./fonts/OFL.txt). Self-hosted rather
 * than `next/font/google` so `next build` (CI, build-release-artifact.sh)
 * never fetches from Google at build time.
 *
 * `display: swap` + `adjustFontFallback` (a metric-matched Arial fallback)
 * keeps the swap free of layout shift. Exposed as `--font-be-vietnam-pro`,
 * read by `--lp-font-sans` (src/styles/tokens.css).
 *
 * No 700: it was used only by the wordmark, and every preloaded face competes
 * with the H1 (the mobile LCP element) for the first bytes — dropping it took
 * the home page from LCP 3.5 s to 2.5 s in a local Lighthouse A/B (P34, AC-34.7).
 */
export const beVietnamPro = localFont({
  src: [
    { path: "./fonts/be-vietnam-pro-regular-latin-vi.woff2", weight: "400", style: "normal" },
    { path: "./fonts/be-vietnam-pro-medium-latin-vi.woff2", weight: "500", style: "normal" },
    { path: "./fonts/be-vietnam-pro-semibold-latin-vi.woff2", weight: "600", style: "normal" },
  ],
  display: "swap",
  variable: "--font-be-vietnam-pro",
  adjustFontFallback: "Arial",
  fallback: ["system-ui", "sans-serif"],
});
