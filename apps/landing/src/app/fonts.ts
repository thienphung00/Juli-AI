import localFont from "next/font/local";

/**
 * Be Vietnam Pro (D44.1), self-hosted: 400/500/600/700, each one woff2 holding
 * the Latin + Vietnamese subsets (Google Fonts' unicode ranges, subset with
 * fonttools from the upstream OFL TTFs — ./fonts/OFL.txt). Self-hosted rather
 * than `next/font/google` so `next build` (CI, build-release-artifact.sh)
 * never fetches from Google at build time.
 *
 * `display: swap` + `adjustFontFallback` (a metric-matched Arial fallback)
 * keeps the swap free of layout shift. Exposed as `--font-be-vietnam-pro`,
 * read by `--lp-font-sans` (src/styles/tokens.css).
 */
export const beVietnamPro = localFont({
  src: [
    { path: "./fonts/be-vietnam-pro-regular-latin-vi.woff2", weight: "400", style: "normal" },
    { path: "./fonts/be-vietnam-pro-medium-latin-vi.woff2", weight: "500", style: "normal" },
    { path: "./fonts/be-vietnam-pro-semibold-latin-vi.woff2", weight: "600", style: "normal" },
    { path: "./fonts/be-vietnam-pro-bold-latin-vi.woff2", weight: "700", style: "normal" },
  ],
  display: "swap",
  variable: "--font-be-vietnam-pro",
  adjustFontFallback: "Arial",
  fallback: ["system-ui", "sans-serif"],
});
