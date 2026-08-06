# ADR-056: Brand assets live in `packages/brand`

**Status:** Accepted (2026-08-06)

Until now the monorepo contained no image assets at all — the Juli logo existed only
in Figma, and neither `apps/demo` nor `apps/dashboard` shipped a `public/` directory.
The `apps/landing` build (Phase 2.7 PRD) introduces the first raster assets: the
Juli AI wordmark, hero photography, and 3D renders extracted from the landing Figma
frames. Three homes were considered: `apps/landing/public/` (app-local; strands
assets in one app and invites copies), an `assets/` folder inside `@juli/ui`
(mixes binary assets into a component package), and a dedicated workspace package.

**Decision:** create **`packages/brand`** (`@juli/brand`) as the single owner of
brand raster/vector assets plus the `<JuliLogo>` React SVG component. Apps import
assets from the package; copying asset files into an app's `public/` is prohibited.
This extends the PRD 2.7 visual-drift mitigation (shared `@juli/theme`/`@juli/ui`)
to imagery: one logo source means a rebrand touches one package. Canonical assets
are processed (background-keyed, resized, web-optimized) from the curated raw
brand set (`Juli-images-unique`, kept outside the repo); the raw set contains
multiple bird/wordmark variants, and exactly one of each is canonical here —
mixing variants is prohibited. Quality upgrades replace files in place (same
filename, no code change).
