# Module: landing

## Responsibility

Public marketing site for `app-juli.com` (Phase 2.7 PRD). Persuades prospective
TikTok Shop sellers and converts them into the Demo — it does not operate a shop.
Static/mock content only; no backend calls, no auth.

## Public interface

- `/` — single-page marketing story: Hero · 4-step strip · market comparison ·
  feature showcase · curiosity CTA · closing CTA · footer.
- `DEMO_URL` (`src/lib/site.ts`) — the one CTA destination
  (`demo.app-juli.com`, Mock mode; `NEXT_PUBLIC_DEMO_URL` overrides for preview).

## Dependencies

- `@juli/brand` — logo lockup + hero/render raster assets (ADR-056).
- `@juli/theme` — semantic tokens; all colors come from here.
- `@juli/ui` — button/badge primitives where they fit the marketing layout.

## Invariants

- **The Demo is the primary CTA everywhere** — header, hero, mid-page, closing.
  "Đăng ký" never appears as a primary action (CONTEXT.md `apps/landing`).
- No pricing section until packaging is decided.
- User-visible copy is Vietnamese with correct diacritics (ADR-028 voice).
- No hardcoded colors — semantic `--juli-*` tokens only.
- Identical content across web and mobile-web breakpoints; only layout adapts.
- Motion respects `prefers-reduced-motion`; interactive targets ≥ 44×44px with
  visible focus states.
- The app never imports a sibling app; feature mockups are rebuilt in code,
  never shipped as flattened UI bitmaps.

## Owners

- domain: web
- code: `apps/landing/`
