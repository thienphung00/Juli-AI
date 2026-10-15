import type { BlogCategory, BlogCover } from "./types";

/**
 * Blog topics, in filter-pill order. `slug` is the pill's value (URL-safe);
 * colours come from the `--lp-cat-<key>-{bg,text,accent}` tokens.
 */
export const BLOG_CATEGORIES: Readonly<Record<BlogCategory, { label: string; slug: string }>> = {
  metrics: { label: "Chỉ số", slug: "chi-so" },
  optimize: { label: "Tối ưu sản phẩm", slug: "toi-uu-san-pham" },
  tools: { label: "Công cụ", slug: "cong-cu" },
  guide: { label: "Hướng dẫn", slug: "huong-dan" },
};

export const BLOG_CATEGORY_ORDER = Object.keys(BLOG_CATEGORIES) as BlogCategory[];

/**
 * The files `scripts/blog-covers.mjs` writes for the cover `name` (an entry of
 * its `COVERS`): `public/media/blog-<name>-{600,1200}.{avif,webp}` (16:9) and
 * `blog-<name>-og.png` (1200×630).
 */
export function blogCover(name: string, alt: string): BlogCover {
  const base = `/media/blog-${name}`;
  return {
    alt,
    variants: [
      { avif: `${base}-600.avif`, webp: `${base}-600.webp`, width: 600, height: 338 },
      { avif: `${base}-1200.avif`, webp: `${base}-1200.webp`, width: 1200, height: 675 },
    ],
    og: { url: `${base}-og.png`, width: 1200, height: 630, alt },
  };
}
