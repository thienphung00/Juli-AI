# Module: landing

## Responsibility

Public marketing site for `app-juli.com` (Phase 2.7 PRD). Persuades prospective
TikTok Shop sellers and converts them into the Demo — it does not operate a shop.
Static/mock content, no auth. It calls no Juli backend: the one server
route it owns (`/api/tt/event`) talks to TikTok, not to `juli-api`.

## Public interface

- `/` — single-page marketing story: Hero (sales demo video, `public/videos/`) ·
  4-step strip · market comparison · feature showcase · closing trial CTA · footer.
- `/privacy`, `/terms` (issue #1971) — hosted privacy policy and terms of service,
  a prerequisite for publishing the Google OAuth consent screen (ADR-094 decision
  3). Linked from the hero's sign-in CTA and the site footer, which both pages
  reuse. Data-handling sections are grounded in what the code demonstrably does;
  entity details (`COMPANY` in `src/lib/site.ts`), retention, rights and
  commercial terms were set by the owner (grill session 2026-10-10).
  `/privacy#du-lieu-nguoi-dung-google` (§3) is the Google OAuth brand-verification
  section: scopes, data accessed, use, Limited Use, sharing, protection,
  retention/deletion/revocation, plus an English summary; tests pin each item.
  Data rights and processing (P42, ToS 2.2 / Privacy 2.1, 16/10/2026): `/terms` §8
  "Dữ liệu của bạn" (ownership, the seller's warranty, seller = controller / Juli =
  processor of buyer data, third-party content, market data, the anonymised
  fine-tune clause); `/privacy` §1 (controller split), §4 (uploads, buyer reviews,
  FastMoss as a market-data source), §6 (purpose limit + fine-tune), §7 (one
  processor list, identical VI/EN, what goes to OpenAI, cross-border safeguards),
  §8 (72 h incident notice). Every processor and AI input was checked against the
  code; `src/__tests__/legal-data-layers.test.tsx` pins them. When a processor
  changes, edit both languages and that test's lists together.
- `/san-pham`, `/about`, `/contact` — public, no-login pages describing the
  product (features, TikTok Shop data use, pricing, FAQ) and the operating
  company (`COMPANY`). `/product` 301s to `/san-pham` (D43.1, `RENAMED_PATHS`
  in `next.config.ts`). Required by TikTok's developer review, which rejected a
  site that was only a landing page plus a login (2026-10, ticket 4486401).
  Header and footer link them from every page (`SITE_PAGES`); the footer
  carries the legal entity, tax ID and address.
- `/sitemap.xml` — every page in the SEO route registry, with `lastmod`.
- `src/lib/seo` — technical SEO (D43.5, P33-A): route registry,
  `buildMetadata()` (title, description, absolute canonical, OG `vi_VN`
  1200×630, Twitter), `<JsonLd>` + schema.org builders (Organization + WebSite
  on every page from the layout, BreadcrumbList, SoftwareApplication/Offer,
  FAQPage, Article, VideoObject). How to add a page: `src/lib/seo/README.md`.
  `pnpm check:seo` checks the built HTML of every registered route.
- `public/media/` — pre-generated AVIF/WebP with known sizes
  (`scripts/media.py`), cached `immutable`; `<Picture>` and `SiteLogo` render them
  with width/height.
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
- Pricing lives on `/san-pham` only, and must match `/terms` section 5; the home
  page states price only as the "từ 500K" entry point.
- No unverifiable claims (partner badges) and no "coming soon" copy on any
  public page.
- User-visible copy is Vietnamese with correct diacritics (ADR-028 voice).
- No hardcoded colors — semantic `--juli-*` tokens only.
- Identical content across web and mobile-web breakpoints; only layout adapts.
- Every page is registered in `src/lib/seo/routes/` and exports
  `metadata = buildMetadata(path)`; one `<h1>`, no skipped heading level; no
  `sameAs`, no hreflang (D43.8). Images carry width/height and ship as
  AVIF/WebP.
- Motion respects `prefers-reduced-motion`; interactive targets ≥ 44×44px with
  visible focus states.
- The app never imports a sibling app; feature mockups are rebuilt in code,
  never shipped as flattened UI bitmaps.
- The Events API token is read from the server process environment and never
  becomes a `NEXT_PUBLIC_*` value — that would publish it in the bundle.
- Analytics runs only with consent (Nghị định 13/2023): `CookieConsent` loads
  the TikTok Pixel and mounts `TikTokTracking` (and so the Events API relay)
  only after the visitor clicks "Đồng ý"; refusing or not answering loads and
  sends nothing. The footer's "Cài đặt cookie" reopens the choice; withdrawing
  clears the pixel's first-party cookies and reloads.
- Analytics never breaks the page: no call into the pixel or the relay may
  throw, and a missing token produces a logged 503, never a silent no-op.

## Owners

- domain: web
- code: `apps/landing/`
