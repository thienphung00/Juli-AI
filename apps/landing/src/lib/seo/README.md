# `src/lib/seo` — technical SEO helpers (D43.5, P33-A)

Every public page of app-juli.com goes through these helpers. Import from
`../lib/seo` (or `../../lib/seo`, …) — never build `Metadata` or JSON-LD by hand.

## Adding a page (P33-B / C / D)

1. **Register it** in the right file under `routes/` (split by owner so parallel
   branches touch different files):
   - `core.ts` — `/`, `/about`, `/contact`, `/privacy`, `/terms`
   - `product.ts` — `/san-pham`
   - `capabilities.ts` — `/san-pham/<slug>` (`parent: "/san-pham"`), `/ket-noi/tiktok-shop`
   - `blog.ts` — `/blog`, `/blog/<slug>` (`parent: "/blog"`, `ogType: "article"`), derived
     from `src/content/blog/posts.ts`; a draft post gets `noindex: true` (robots
     `noindex, follow`, no sitemap entry, `check:seo` asserts the noindex and that no
     indexable page links it). See `src/content/blog/README.md`.

   ```ts
   {
     path: "/san-pham/phan-tich-shop",
     title: "Phân tích shop TikTok Shop theo luồng truy cập | Juli AI", // ≤ 60, "<Benefit> | Juli AI"
     description: "…",            // 70–155 characters, unique
     lastModified: "2026-10-16",  // bump on every content change (sitemap lastmod)
     breadcrumbName: "Phân tích shop",
     parent: "/san-pham",         // default "/"
     changeFrequency: "monthly",
     priority: 0.8,
     // ogImage: { url: "/og/phan-tich-shop-v1.png", width: 1200, height: 630, alt: "…" },
   }
   ```
   The sitemap reads the registry; nothing else to do there.

2. **Metadata** in the page:
   ```ts
   import { buildMetadata } from "../../lib/seo";
   export const metadata = buildMetadata("/san-pham/phan-tich-shop");
   // Blog post: buildMetadata(path, { publishedTime: "2026-10-20", modifiedTime, authors: ["Juli AI"] })
   ```
   Gives `<title>` (absolute, no template), description, absolute self canonical,
   Open Graph (`vi_VN`, site name, 1200×630 image, `website` or `article`) and a
   `summary_large_image` Twitter card. An unregistered path throws at build.

3. **JSON-LD** in the page body (Organization + WebSite are already on every
   page from `app/layout.tsx` — do not repeat them):
   ```tsx
   import { breadcrumbSchema, faqPageSchema, JsonLd, softwareApplicationSchema } from "../../lib/seo";

   <JsonLd data={[
     breadcrumbSchema("/san-pham/phan-tich-shop"),          // every inner page
     softwareApplicationSchema({ path: "/san-pham/phan-tich-shop" }), // product pages
     faqPageSchema(FAQ),                                    // ONLY the FAQ rendered on this page
   ]} />
   ```
   Other builders: `articleSchema({ path, datePublished, dateModified?, image?, authorName? })`,
   `videoObjectSchema(input)` (`HERO_VIDEO_SCHEMA` in `src/lib/media.ts` is ready-made
   for the hero video), `organizationSchema()`, `websiteSchema()`.

4. **Headings**: exactly one `<h1>`, then H2 → H3 without skipping a level
   (`<h2>` → `<h4>` fails). The header/footer have no headings.

5. **Images**: pre-generate AVIF + WebP with known sizes, never ship a raw PNG/JPG:
   ```bash
   /Users/macos/Juli-AI-v2/juli/.venv/bin/python apps/landing/scripts/media.py optimize shot.png \
     --out apps/landing/public/media/phan-tich-shop-tong-quan-v1 --widths 640,1280
   ```
   Then add a `MediaSource[]` constant and render
   `<Picture variants={…} alt="… (dữ liệu mẫu)" sizes="(min-width: 960px) 880px, 100vw" />`
   (`src/components/picture.tsx`; `priority` only for the LCP image). Files in
   `public/media/` are cached `immutable` for a year: **never overwrite one** —
   bump `-v1` → `-v2`.

6. **Check** before you hand over:
   ```bash
   pnpm --filter @juli/landing test          # registry: every page registered, titles/descriptions sized + unique
   pnpm --filter @juli/landing build && pnpm --filter @juli/landing check:seo   # built HTML of every route
   ```
   `check:seo` (`src/seo-check/built-site.check.ts`) fails on: ≠ 1 h1, skipped heading
   level, title/description/canonical missing, different from the registry or
   duplicated, no OG image / Twitter card, hreflang, noindex (a `noindex` blog draft must be noindex instead), JSON-LD that does
   not parse, missing Organization/WebSite/BreadcrumbList, an FAQPage question
   not visible on the page, any `sameAs`. `SEO_BASE_URL=http://localhost:3007`
   checks a running server instead of `.next/server/app/*.html`.

## Rules (D43.5, D43.8)

- No `sameAs`, no social links, no hreflang / `alternates.languages`, no `/en`.
- FAQPage only for questions rendered on the same page; no Review/AggregateRating
  (no testimonials until real customers exist, D43.3).
- Renamed URLs: add `{ source, destination }` to `RENAMED_PATHS` in
  `next.config.ts` (301). Unknown URLs stay 404 — never redirect them to home.
- Home canonical is the bare origin `https://app-juli.com` (what Next prints).

## Files

| File | What |
|---|---|
| `config.ts` | `SITE_URL`, `SITE_NAME`, `OG_LOCALE`, `DEFAULT_OG_IMAGE`, limits, `absoluteUrl()` |
| `routes/` | the registry: `SITE_ROUTES`, `getRoute()`, `hasRoute()`, `breadcrumbTrail()` |
| `metadata.ts` | `buildMetadata(path, options?)`, `ROOT_METADATA` (layout) |
| `schema.ts` | JSON-LD builders |
| `json-ld.tsx` | `<JsonLd data>` + `serializeJsonLd()` (escapes `<`) |
