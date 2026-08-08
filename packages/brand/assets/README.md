# Brand assets

Canonical Juli brand rasters (ADR-056), processed for web from the curated
brand set (`Juli-images-unique`, maintained outside the repo; see its
`ASSETS.md`/`_manifest.csv` for provenance and the full raw catalog).

| File | Source (raw set) | Processing |
|------|------------------|------------|
| `logo-wordmark.png` | `logo-upscale-retouch.png` | background keyed to transparent, trimmed, 649×213 |
| `bird-glyph.png` | `magnific_minimalist-and-simplistic_hEWqR2fvqL.png` | background keyed to transparent, trimmed, 512px |
| `hero-mascot.webp` | `ChatGPT Image Jun 28, 2026, 11_28_15 AM.png` | 1600×900, WebP q82 (no baked headline copy) |

Rules:

- **One bird, one wordmark.** The raw set contains multiple subtly-different
  bird and wordmark variants; only the two above are canonical. Do not import
  others without deliberately re-deciding the mark.
- Keep filenames exactly as listed — imports depend on them
  (`BRAND_ASSETS` in `src/index.ts`).
- Quality upgrades overwrite in place (same name).
- Full-infographic banners with baked-in Vietnamese copy (e.g.
  `hero-banner-original.png`) must not ship on pages — baked text is invisible
  to screen readers and cannot be localized.
- No app-specific imagery here; that belongs to the app that owns it.
