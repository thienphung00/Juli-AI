# Module: landing

## Responsibility

Public marketing site for `app-juli.com` (Phase 2.7 PRD). Persuades prospective
TikTok Shop sellers and converts them into the Demo — it does not operate a shop.
Static/mock content, no auth. It calls no Juli backend: the one server
route it owns (`/api/tt/event`) talks to TikTok, not to `juli-api`.

## Public interface

- `/` — single-page marketing story: Hero · 4-step strip · market comparison ·
  feature showcase · curiosity CTA · closing CTA · footer.
- `/privacy`, `/terms` (issue #1971) — hosted privacy policy and terms of service,
  a prerequisite for publishing the Google OAuth consent screen (ADR-094 decision
  3). Linked from the hero's sign-in CTA and the site footer, which both pages
  reuse. Content is owner-led: data-handling sections are grounded in what the
  code demonstrably does; legal-specific fields (entity details, retention,
  jurisdiction, liability, warranty) are explicit `[OWNER: ...]` placeholders
  (`OwnerPlaceholder` component) pending owner and legal review — not invented.
- `DEMO_URL` (`src/lib/site.ts`) — the one CTA destination
  (`demo.app-juli.com`, Mock mode; `NEXT_PUBLIC_DEMO_URL` overrides for preview).
- `POST /api/tt/event` — the TikTok Events API relay. Same-origin, so an ad
  blocker that stops the pixel does not stop this. Accepts only this site's
  own origins (`SITE_ORIGINS`) and only the events in
  `@juli/tiktok-events`'s allowlist.

## Dependencies

- `@juli/brand` — logo lockup + hero/render raster assets (ADR-056).
- `@juli/theme` — semantic tokens; all colors come from here.
- `@juli/ui` — button/badge primitives where they fit the marketing layout.
- `@juli/tiktok-events` — pixel, event vocabulary, and the relay handler.

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
- The Events API token is read from the server process environment and never
  becomes a `NEXT_PUBLIC_*` value — that would publish it in the bundle.
- Analytics never breaks the page: no call into the pixel or the relay may
  throw, and a missing token produces a logged 503, never a silent no-op.

## Owners

- domain: web
- code: `apps/landing/`
