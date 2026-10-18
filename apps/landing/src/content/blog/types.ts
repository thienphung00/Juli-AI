import type { MediaSource } from "../../lib/media";
import type { FaqItem, OgImage } from "../../lib/seo";

/**
 * `draft`: rendered at its URL (so the owner can review it and `check:seo`
 * covers it) but `noindex`, out of the sitemap and not listed on `/blog` in
 * production. `published`: indexed, in the sitemap, listed. Flipping this one
 * field is how the owner approves a post — see ./README.md.
 */
export type BlogPostStatus = "draft" | "published";

/**
 * Blog topic (Blog.dc.html filter pills + cover tint): Chỉ số = pink,
 * Tối ưu sản phẩm = green, Công cụ = blue, Hướng dẫn = grey. Labels and
 * colours: `BLOG_CATEGORIES` (./covers.ts) and the `--lp-cat-<key>-*` tokens.
 */
export type BlogCategory = "metrics" | "optimize" | "tools" | "guide";

/**
 * A post's cover (D59.3): the post's own hero illustration, rendered by the
 * `BlogHero` still in juli-content-engine and converted by `scripts/media.py
 * blog-hero`. Build it with `blogCover()`.
 */
export interface BlogCover {
  /** 16:9 AVIF + WebP, 600 and 1200 wide, with their intrinsic sizes. */
  variants: readonly MediaSource[];
  /** What the picture shows (the post page renders it with this alt; cards use alt=""). */
  alt: string;
  /** 1200×630 PNG of the same cover for Open Graph / Twitter. */
  og: OgImage;
}

/**
 * An inline figure in a post body (D48 additions 7, P39-C), placed with a
 * `{{hinh:<id>}}` line and defined in `./figures.ts`. Always lazy-loaded and
 * never prioritised: the post's H1 stays the LCP.
 */
export interface BlogFigure {
  /**
   * `diagram`: rendered from HTML by `scripts/blog-diagrams.mjs` (any number in
   * it is labelled "Ví dụ giả định"). `screenshot`: a real Juli screen on the
   * sample shop "Cửa hàng Mẫu Hoa Mai" (`public/media/cap-*`), framed and
   * captioned "Dữ liệu mẫu" like the product pages.
   */
  kind: "diagram" | "screenshot";
  /** Desktop variants (AVIF + WebP, intrinsic width/height). */
  variants: readonly MediaSource[];
  /** Phone variants (≤ 640 px): own layout or crop so the text stays legible. */
  mobileVariants: readonly MediaSource[];
  /** Vietnamese; says everything the picture says (it carries text). */
  alt: string;
  /** Visible Vietnamese caption. A screenshot's starts with "Dữ liệu mẫu · ". */
  caption: string;
}

/**
 * A cited source (D56 G2). Primary sources (TikTok Academy / Seller University,
 * Shopee Seller Education, ads.tiktok.com help, laws, government portals) carry
 * their `url` and render as a link. A competitor or vendor page (any domain in
 * `./competitors.ts`) is cited WITHOUT a URL: name + `checkedAt`, rendered as
 * plain text "<title> (<note>, kiểm tra DD/MM/YYYY)".
 */
export type BlogSource = LinkedBlogSource | UnlinkedBlogSource;

interface BlogSourceBase {
  /** Page title as the source shows it (TikTok Academy title, vendor page name). */
  title: string;
  /** What we took from it, or when it was checked (`kiểm tra 15/10/2026`). */
  note?: string;
}

export interface LinkedBlogSource extends BlogSourceBase {
  url: string;
  checkedAt?: undefined;
}

export interface UnlinkedBlogSource extends BlogSourceBase {
  url?: undefined;
  /** `YYYY-MM-DD` the page was read; shown as "kiểm tra DD/MM/YYYY". */
  checkedAt: string;
}

/**
 * Post type (D56 G5): decides the word range and the FAQ rule
 * (`blog.test.tsx`, README "Writing a post").
 * - `pillar`: a topic's main page, 3,000+ words.
 * - `comparison`: tools hub and tool comparisons, 3,000+ words.
 * - `pain`: a seller pain point / long-tail question, 1,500–2,500 words (soft cap 3,000).
 * - `news`: a TMĐT change (fees, policy, tax, regulation), 800–1,500 words (soft cap 2,000).
 * - `guide`: a Juli how-to / feature guide (D59), 1,500–3,000 words, FAQ 3–5, 3–8 figures.
 *
 * The format also decides the post's tier (D59, `blogTier()` in ./index.ts):
 * pain and news are `reach` (no Juli anywhere in the post), pillar, comparison
 * and guide are `conversion` (may describe Juli and show its UI).
 */
export type BlogPostFormat = "pillar" | "comparison" | "pain" | "news" | "guide";

/**
 * D59 content tier, derived from `format` (never stored on a post):
 * - `reach`: search intent, top of funnel. No "Juli" in body, FAQ, figures or
 *   meta, no `cap-*` screenshots, no links to `/san-pham*`, `/ket-noi/*`,
 *   `/dang-ky` or the demo; the page ends with the neutral calculator box.
 * - `conversion`: may describe Juli and show its UI (within SPEC); the page
 *   ends with the Juli trial / demo CTA.
 */
export type BlogTier = "reach" | "conversion";

/**
 * One blog post's metadata. Light on purpose: the route registry imports it,
 * the body lives in `./bodies/<slug>.ts` and is loaded only by the post page.
 */
export interface BlogPostMeta {
  /** URL slug: `/blog/<slug>`. Vietnamese without diacritics, hyphenated. */
  slug: string;
  /** THE approval flag (owner only). */
  status: BlogPostStatus;
  /** The visible H1. */
  title: string;
  /** `<title>`: "<…> | Juli AI", ≤ 60 characters, unique. */
  seoTitle: string;
  /** Meta description, 70–155 characters, unique. */
  description: string;
  /** One or two sentences under the title and on the `/blog` index. */
  excerpt: string;
  /** Short breadcrumb label. */
  breadcrumbName: string;
  /** `YYYY-MM-DD`. Set to the publication day when the post is approved. */
  publishedAt: string;
  /** `YYYY-MM-DD`, ≥ publishedAt. Bump on every content change (sitemap lastmod). */
  updatedAt: string;
  /** Topic: filter pill, label colour and cover tint. */
  category: BlogCategory;
  /** Post type (D56 G5): word range and FAQ rule. */
  format: BlogPostFormat;
  /** Cover image + its OG variant. */
  cover: BlogCover;
  /** "Đội ngũ Juli AI" unless the owner names a person. */
  author: string;
  /** Slugs of related posts (only published ones are shown on a published post). */
  related: readonly string[];
  /**
   * Reach posts only (D59 addition 4): the conversion guide the end-of-post box points to, with a
   * neutral "Đọc hướng dẫn liên quan" line. Never linked from the body.
   */
  guide?: string;
  /** Questions rendered at the end of the post; they become FAQPage JSON-LD. */
  faq?: readonly FaqItem[];
  /** Rendered as "Nguồn tham khảo". */
  sources: readonly BlogSource[];
}

export interface BlogPost extends BlogPostMeta {
  /** Markdown subset, see `src/components/blog/markdown.tsx`. Starts at `##` (the H1 is `title`). */
  body: string;
}
