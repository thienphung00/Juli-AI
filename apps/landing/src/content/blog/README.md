# Blog content (`/blog`, D43.7)

Posts are TypeScript files rendered on the server at build time (no client JS
for content, no MDX dependency).

| File | What |
|---|---|
| `posts.ts` | Every post's metadata: **`status`**, title, SEO title/description, dates, author, FAQ, sources, related posts |
| `bodies/<slug>.ts` | The post body (Markdown subset, starts at `##`; the H1 is `title`) |
| `bodies/index.ts` | slug → body map |
| `types.ts` | `BlogPostMeta`, `BlogPost`, `BlogPostStatus`, `BlogPostFormat`, `BlogTier`, `BlogSource`, `BlogCategory`, `BlogCover` |
| `competitors.ts` | `COMPETITORS` (D56 G1 rings: direct, adjacent, not-competing; names and domains), `isCompetitorUrl`, `competitorNamesIn` |
| `covers.ts` | `BLOG_CATEGORIES` (topic labels, pill order) and `blogCover(name, alt)` |
| `index.ts` | helpers: `getPost`, `relatedPosts`, `showDraftsOnIndex`, `blogTier` / `FORMAT_TIER`, … |

Pages: `src/app/blog/page.tsx` (index: H1, topic pills, featured card, 3-up grid),
`src/app/blog/[slug]/page.tsx` (post: cover, side TOC, FAQ, sources, related cards,
dark end-of-post CTA by tier, see below), `src/app/blog/blog.css`. Renderer: `src/components/blog/markdown.tsx`;
cards `post-card.tsx`; pills `category-filter.tsx` (the only client JS). Routes:
`src/lib/seo/routes/blog.ts` derives `/blog` and one route per post from
`posts.ts` — nothing to register by hand.

## Draft vs published

| | `status: "draft"` | `status: "published"` |
|---|---|---|
| URL `/blog/<slug>` | renders (banner "Bản nháp đang chờ duyệt") | renders |
| robots meta | `noindex, follow` | indexable |
| `sitemap.xml` | absent | present, `lastmod` = `updatedAt` |
| listed on `/blog` | only under `pnpm dev` ("Bản nháp chờ duyệt") | yes |
| linked from other posts | only from other drafts; a published post shows the link text unlinked and leaves it out of "Bài viết liên quan" | yes |
| `check:seo` | asserts it **is** noindex | asserts it is indexable, and that it links no draft |

## How the owner approves a post

1. Review the draft: `pnpm --filter @juli/landing dev`, open
   `http://localhost:3007/blog` (drafts are listed there in dev) or the post URL
   directly. Edit the body in `bodies/<slug>.ts` if needed.
2. In `posts.ts`, change that post's **`status: "draft"` → `status: "published"`**.
   This single field is the approval.
3. Set `publishedAt` (and `updatedAt`) to the publication day, `YYYY-MM-DD`.
4. Commit with the approval in the message, e.g.
   `docs(blog): publish chi-so-tiktok-shop-ctr-ctor-aov (owner approved 2026-10-20)`,
   and add a line to `fasttrack/LOG.md`. That commit is the approval record
   AC-33.8 asks for.
5. Run the gates: `pnpm --filter @juli/landing test` and
   `pnpm --filter @juli/landing build && pnpm --filter @juli/landing check:seo`,
   then deploy as usual.

To unpublish, set the status back to `"draft"`: the page stays reachable but
becomes noindex and leaves the sitemap and the index.

## Reach vs conversion (D59)

Every post has a tier, derived from its `format` by `blogTier(post)`
(`FORMAT_TIER` in `index.ts`); it is never a field of its own.

| Tier | Formats | Juli in the post | End-of-post CTA |
|---|---|---|---|
| `reach` (search intent, top of funnel) | `pain`, `news` | **none** | neutral box `blog-cta-tool`: "Tự tính GMV và tìm bước yếu nhất", button to `/cong-cu/tinh-gmv`, link to `/blog` |
| `conversion` | `pillar`, `comparison`, `guide` | may describe Juli and show its UI, within SPEC | Juli trial + demo (`blog-cta-trial`, `blog-cta-demo`) |

Rules for a **reach** post (test, "reach vs conversion tier (D59)"):

- No "Juli" (any case) in the body, `title`, `seoTitle` (apart from the site-wide
  ` | Juli AI` suffix), `description`, `excerpt`, `breadcrumbName`, the cover alt,
  the FAQ, or the alt / caption of its figures. No feature descriptions.
- Figures are diagrams only: no "Dữ liệu mẫu" `cap-*` screenshots.
- No links to `/san-pham*`, `/ket-noi/*`, `/dang-ky`, the demo (`DEMO_URL`) or
  any `app-juli.com` URL. Instead it links at least two distinct onward targets
  among other blog posts and the free GMV calculator `/cong-cu/tinh-gmv`.
- The rendered page says "Juli" only in the site header and footer, the author
  byline (organisation name) and the "Bài viết liên quan" cards (which may be
  conversion posts).

`REACH_JULI_PENDING` in `blog.test.tsx` is a **temporary** allow-list of the reach
posts written before D59 that still mention Juli (P48-B/C strip them); the body
rules and the onward-link minimum skip those slugs, and a test fails when a
listed post is already clean, so remove a slug as soon as its post is stripped.
The CTA is decided by the tier, so every reach post already ends with the
neutral box. The two Juli-free comparison posts (đa kênh, AI ảnh/video) stay
conversion-tier and keep their own `NO_JULI_IN_BODY` rule.

## Writing a post (D56 standard)

The rules come from `fasttrack/content-plan.md` (G1, G2, G5); `blog.test.tsx`
checks the ones marked (test).

- **Files.** A meta entry in `posts.ts` (`seoTitle` ≤ 60 characters ending in
  ` | Juli AI`, `description` 70–155 characters, both unique (test);
  `status: "draft"`), a body file in `bodies/`, and its line in `bodies/index.ts`.
- **Format and length** (`format` in `posts.ts`, test). Words are counted by
  `countWords` (visible text, Markdown stripped):

  | `format` | What | Words |
  |---|---|---|
  | `pillar` | a topic's main page (GMV, chỉ số, thẻ sản phẩm) | 3,000+ |
  | `comparison` | tools hub and tool comparisons (category `tools`) | 3,000+ |
  | `pain` | a seller pain point / long-tail question | 1,500–2,500 (fails above 3,000) |
  | `news` | a TMĐT change: fees, policy, tax, regulation | 800–1,500 (fails above 2,000) |
  | `guide` | a Juli how-to / feature guide (D59, conversion tier) | 1,500–3,000 (fails above 3,000) |

  The upper limits apply to posts written after D56; the posts listed in
  `PRE_D56_POSTS` keep their length. At least 5 H2s (3 for `news`), H2 → H3
  only, unique headings (test).
- **Opening.** The first 2–3 sentences answer the pain in the seller's own
  words; then explain with the method (in a reach post without naming Juli) (Lượt hiển thị × CTR × CTOR × AOV by
  traffic source, change only after approval, measure day 7 / 14). H2 / H3 come
  from real seller questions.
- **Primary sources, linked.** TikTok Academy VN / Seller University, Shopee
  Seller Education, ads.tiktok.com help, laws and decrees, government portals:
  cited by title in the text and in `sources` with their `url`. A `news` post
  uses only official sources found on the day, each dated.
- **Competitor and vendor sources, unlinked** (test). Any domain in
  `competitors.ts` (all three rings) is never linked, in the body or in
  `sources`: cite it with `vendor("Sapo: Bảng giá", "2026-10-16")` (title +
  `checkedAt`, no `url`), rendered as plain text "Sapo: Bảng giá (kiểm tra
  16/10/2026)". The post page also unlinks such a URL if one slips in.
- **Competitor names** (G1, test). `direct` ring (Sapo, Shopee "Tối ưu sản phẩm
  bởi AI", Atosa, FastMoss, Kalodata, Metric): only in posts of category
  `tools`, one factual line per tool, never a reason to choose them over Juli.
  `adjacent` ring (AI chatbots / AI sales agents): never named; write
  "chatbot trả lời tin nhắn". `not-competing` (CapCut, Canva, multichannel
  software…): named normally, not linked. No copied feature lists or price
  tables beyond one factual line per tool; prices only as the vendor publishes them.
- **Figures.** 3–6 per new post (diagrams, and "Dữ liệu mẫu" screenshots in
  conversion posts only, see below); the test allows 0–8 per post, 3–8 for a
  `guide`, and every figure in `figures.ts` must be used.
- **FAQ.** 3–5 questions (test for new `pain` / `news` posts and every `guide`),
  they become FAQPage JSON-LD. The end-of-post CTA comes from the tier; a reach
  post's body has no product CTA.
- **Words and numbers.** Vietnamese only; TikTok's own metric names (Lượt hiển
  thị sản phẩm, CTR, CTOR, Đơn hàng SKU, AOV); numbers in examples marked "Ví dụ
  giả định"; no invented statistics; no "—" (test); facts about Juli within SPEC.
- **Body syntax.** `##` / `###` headings only (no `#`, no `####`), paragraphs,
  `- ` and `1. ` lists, `> ` callouts, `| a | b |` tables with a `|---|---|`
  row, `**bold**`, `[text](/path)` or `[text](https://…)`, `{{hinh:<id>}}`
  figures. No backticks.
- **Internal links.** A reach post: see "Reach vs conversion" above. A
  conversion post links the product pages (`/san-pham`,
  `/san-pham/phan-tich-shop`, `/san-pham/de-xuat-va-thuc-thi`,
  `/san-pham/do-luong-gmv`, `/ket-noi/tiktok-shop`); every internal link must
  resolve (test).
- **After publishing.** The weekly Search Console report (`scripts/seo/gsc_report`,
  section 8) lists every `/blog/*` and `/cong-cu/*` URL with flags; at 8 weeks it
  flags the post for review. After the review, bump `updatedAt` (that clears the flag).

## Topic and cover (D44.3, P34-D)

Every post has a `category` (`metrics` Chỉ số · `optimize` Tối ưu sản phẩm ·
`tools` Công cụ · `guide` Hướng dẫn) and a `cover`. The cover is the post's own
hero image (below); the same image is the post's Open Graph / Twitter image
(1200×630) and goes into the Article JSON-LD.

### Hero images (D59.3, P48-H)

Each post has its own illustration: one vector metaphor for the topic, its own
palette from the landing tokens and its own composition, plus a 2–5-word
Vietnamese kicker in Be Vietnam Pro. No Juli UI or logo, no platform logos or
UI, no photos. They are not drawn here: they come from the sibling repo
`juli-content-engine` (Remotion), still `BlogHero` in
`my-video/src/stills/blog-hero/`, one spec per slug in
`projects/blog-heroes/heroes.json`.

To add one for a new post:

1. In `juli-content-engine`, add an entry to `projects/blog-heroes/heroes.json`
   (`slug`, `kicker`, `motif`, `layout`, `backdrop`, `palette`; a new metaphor
   means a new motif in `motifs.tsx`). Pick a motif, palette and layout that no
   other post uses.
2. Render it: `cd my-video && npm run hero:render -- ../projects/blog-heroes/heroes.json --only <slug> --contact-sheet`
   → `projects/blog-heroes/output/<slug>-hero.png` (2400×1350) and `<slug>-og.png`
   (1200×630). Check the contact sheet, so no two heroes look alike.
3. Here, from the repo root:
   `juli/.venv/bin/python apps/landing/scripts/media.py blog-hero <slug>-hero.png <slug>-og.png --name hero-<slug>-v1`
   → `public/media/blog-hero-<slug>-v1-{600,1200}.{avif,webp}` + `-og.png`. It
   checks the sizes and refuses to overwrite (`immutable` cache): to change a
   hero, render again and use `-v2`.
4. In `posts.ts`: `cover: blogCover("hero-<slug>-v1", "Minh hoạ: …")`. The alt
   describes the picture, kicker included (no "Juli" in a reach post); cards render
   it with `alt=""` because the title is right there. `blog.test.tsx` checks the
   files exist, the 16:9 sizes, one cover per post and the OG image.

## Inline figures (D48 additions 7, P39-C)

A body line `{{hinh:<id>}}` renders the figure `<id>` of `figures.ts`
(`BLOG_FIGURES`): a `<figure>` with a visible `<figcaption>`, AVIF/WebP with
width/height, a phone variant below 640 px, always `loading="lazy"` and never
`priority` (the H1 stays the LCP). The Article JSON-LD `image` stays the cover.
Renderer: `src/components/blog/figure.tsx`.

- **Diagram** (`diagram(name, height, mobileHeight, { alt, caption })`): built in
  HTML by `scripts/blog-diagrams.mjs` (Be Vietnam Pro, landing tokens, Vietnamese
  only) in a 720 px desktop layout and a 360 px phone layout, so the text in the
  image stays legible on both. Any number in it is hypothetical and the image
  carries the pill "Ví dụ giả định" (say so in the alt and caption too). To add
  one: add an entry to `DIAGRAMS` (name ends `-v1`), run
  `PYTHON=juli/.venv/bin/python node apps/landing/scripts/blog-diagrams.mjs`
  (preview first with `--samples <dir>`), copy the printed heights into
  `figures.ts`. Existing files are never overwritten: bump `-vN` to change one.
- **Screenshot** (`screenshot(variants, mobileVariants, { alt, caption })`): only
  real Juli screens on the sample shop (the `public/media/cap-*` files and their
  mobile crops in `components/product/screens.ts`), in the product pages' framed
  `Shot`. The caption starts "Dữ liệu mẫu · ", the alt ends "(dữ liệu mẫu)".
- Never stock photos, TikTok or Shopee screenshots, logos or UI copies, invented
  results, or "—" in alt or caption. The alt says everything the picture says.

`blog.test.tsx` checks each figure's files and their real sizes, the alt and
caption, that every figure renders lazy with a phone source, and that only the
cover is eager; `check:seo` repeats the eager / sized check on the built posts.

### Reach → guide link (D59 addition 4, P49-L)

A reach post never links a Juli page or guide from its body. Its `guide` field names one
conversion guide (`format: "guide"`); the neutral end-of-post box then shows one line
"Đọc hướng dẫn liên quan" to it. `guideFor()` hides the line when a published reach post would
point at a draft guide. Tests: every reach post has a guide, conversion posts have none, the box
has no "Juli" text.
