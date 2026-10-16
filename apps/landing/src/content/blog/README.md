# Blog content (`/blog`, D43.7)

Posts are TypeScript files rendered on the server at build time (no client JS
for content, no MDX dependency).

| File | What |
|---|---|
| `posts.ts` | Every post's metadata: **`status`**, title, SEO title/description, dates, author, FAQ, sources, related posts |
| `bodies/<slug>.ts` | The post body (Markdown subset, starts at `##`; the H1 is `title`) |
| `bodies/index.ts` | slug → body map |
| `types.ts` | `BlogPostMeta`, `BlogPost`, `BlogPostStatus`, `BlogCategory`, `BlogCover` |
| `covers.ts` | `BLOG_CATEGORIES` (topic labels, pill order) and `blogCover(name, alt)` |
| `index.ts` | helpers: `getPost`, `relatedPosts`, `showDraftsOnIndex`, … |

Pages: `src/app/blog/page.tsx` (index: H1, topic pills, featured card, 3-up grid),
`src/app/blog/[slug]/page.tsx` (post: cover, side TOC, FAQ, sources, related cards,
dark CTA), `src/app/blog/blog.css`. Renderer: `src/components/blog/markdown.tsx`;
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

## Writing a post

- Add a meta entry to `posts.ts` (`seoTitle` ≤ 60 characters ending in
  ` | Juli AI`, `description` 70–155 characters, both unique; `status: "draft"`),
  a body file in `bodies/`, and its line in `bodies/index.ts`.
- Body syntax: `##` / `###` headings only (no `#`, no `####`), paragraphs,
  `- ` and `1. ` lists, `> ` callouts, `| a | b |` tables with a `|---|---|`
  row, `**bold**`, `[text](/path)` or `[text](https://…)`. No backticks.
- Use TikTok's own Vietnamese metric names (Lượt hiển thị sản phẩm, CTR, CTOR,
  Đơn hàng SKU, AOV). Cite TikTok Academy pages by title in the text and in
  `sources`. No invented statistics: a worked example says it is hypothetical.
- Facts about third-party tools come from the vendor's own site, dated
  ("kiểm tra 15/10/2026"); no prices unless the vendor publishes them.
- Link the product pages (`/san-pham`, `/san-pham/phan-tich-shop`,
  `/san-pham/de-xuat-va-thuc-thi`, `/san-pham/do-luong-gmv`,
  `/ket-noi/tiktok-shop`). `blog.test.tsx` checks every internal link resolves
  and every post is 3,000+ words.

## Topic and cover (D44.3, P34-D)

Every post has a `category` (`metrics` Chỉ số · `optimize` Tối ưu sản phẩm ·
`tools` Công cụ · `guide` Hướng dẫn) and a `cover`. The cover is a flat
category tint with one simple outlined object and exactly one accent, **no
text**, rendered from HTML by Playwright; the same render is the post's
Open Graph / Twitter image (1200×630) and goes into the Article JSON-LD.

To make a cover for a new post:

1. Add an entry to `COVERS` in `apps/landing/scripts/blog-covers.mjs`:
   `{ name: "<short-name>-v1", category: "tools", accent: 2 }` (`motif` defaults to
   the category's: bars / card / tiles / checklist; `accent` picks which element
   carries the accent colour, so two posts in one topic differ).
2. From the repo root (Node 20):
   `PYTHON=juli/.venv/bin/python node apps/landing/scripts/blog-covers.mjs`
   → `public/media/blog-<name>-{600,1200}.{avif,webp}` + `blog-<name>-og.png`.
   Existing files are skipped, never overwritten (`immutable` cache): to change a
   cover, bump `-v2`. Preview every motif without touching `public/`:
   `node apps/landing/scripts/blog-covers.mjs --samples /tmp/covers`.
3. In `posts.ts`: `category: "tools"`, `cover: blogCover("<short-name>-v1", "Minh hoạ: …")`
   (the alt describes the picture; cards render it with `alt=""` because the title
   is right there). `blog.test.tsx` checks the files exist and the OG image is set.

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
