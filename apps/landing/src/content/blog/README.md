# Blog content (`/blog`, D43.7)

Posts are TypeScript files rendered on the server at build time (no client JS
for content, no MDX dependency).

| File | What |
|---|---|
| `posts.ts` | Every post's metadata: **`status`**, title, SEO title/description, dates, author, FAQ, sources, related posts |
| `bodies/<slug>.ts` | The post body (Markdown subset, starts at `##`; the H1 is `title`) |
| `bodies/index.ts` | slug → body map |
| `types.ts` | `BlogPostMeta`, `BlogPost`, `BlogPostStatus` |
| `index.ts` | helpers: `getPost`, `relatedPosts`, `showDraftsOnIndex`, … |

Pages: `src/app/blog/page.tsx` (index), `src/app/blog/[slug]/page.tsx` (post),
`src/app/blog/blog.css`. Renderer: `src/components/blog/markdown.tsx`. Routes:
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
