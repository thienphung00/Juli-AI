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
 * A post's cover (D44.3): flat tint + one outlined object, no text, rendered
 * from HTML by `scripts/blog-covers.mjs`. Build it with `blogCover()`.
 */
export interface BlogCover {
  /** 16:9 AVIF + WebP, 600 and 1200 wide, with their intrinsic sizes. */
  variants: readonly MediaSource[];
  /** What the picture shows (the post page renders it with this alt; cards use alt=""). */
  alt: string;
  /** 1200×630 PNG of the same cover for Open Graph / Twitter. */
  og: OgImage;
}

export interface BlogSource {
  /** Page title as the source shows it (TikTok Academy title, vendor page name). */
  title: string;
  url: string;
  /** What we took from it, or when it was checked (`kiểm tra 15/10/2026`). */
  note?: string;
}

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
  /** Cover image + its OG variant. */
  cover: BlogCover;
  /** "Đội ngũ Juli AI" unless the owner names a person. */
  author: string;
  /** Slugs of related posts (only published ones are shown on a published post). */
  related: readonly string[];
  /** Questions rendered at the end of the post; they become FAQPage JSON-LD. */
  faq?: readonly FaqItem[];
  /** Rendered as "Nguồn tham khảo". */
  sources: readonly BlogSource[];
}

export interface BlogPost extends BlogPostMeta {
  /** Markdown subset, see `src/components/blog/markdown.tsx`. Starts at `##` (the H1 is `title`). */
  body: string;
}
