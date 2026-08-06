# Module: brand

## Responsibility

Single owner of Juli brand raster/vector assets — logo lockup, hero photography,
3D renders — per [ADR-056](../../docs/adr/056-brand-asset-package.md). Apps import
from this package; asset files are never copied into an app's `public/`.

## Public interface

- `JuliLogo` — bird glyph + "Juli AI" wordmark lockup (SVG, token-driven colors,
  `variant: "full" | "glyph"`).
- `BRAND_ASSETS` — canonical asset filename map.
- `@juli/brand/assets/*` — raster assets (see `assets/README.md` for the
  expected files and their provenance).

## Invariants

- Colors inside vector marks come from `@juli/theme` tokens (`--juli-primary`,
  `--juli-primary-soft`) — never hardcoded hex.
- Asset filenames are stable; quality upgrades (e.g. 3x Figma re-exports)
  replace files in place with no code change.
- No app-specific content — anything here must make sense for every surface.

## Owners

- domain: web
- code: `packages/brand/`
