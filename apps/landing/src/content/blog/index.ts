import { BLOG_BODIES } from "./bodies";
import { BLOG_POSTS } from "./posts";
import type { BlogPost, BlogPostMeta } from "./types";

export { BLOG_POSTS } from "./posts";
export { BLOG_CATEGORIES, BLOG_CATEGORY_ORDER, blogCover } from "./covers";
export { BLOG_FIGURES } from "./figures";
export type {
  BlogCategory,
  BlogCover,
  BlogFigure,
  BlogPost,
  BlogPostMeta,
  BlogPostStatus,
  BlogSource,
} from "./types";

export function isPublished(post: Pick<BlogPostMeta, "status">): boolean {
  return post.status === "published";
}

export function getPostMeta(slug: string, posts: readonly BlogPostMeta[] = BLOG_POSTS): BlogPostMeta | undefined {
  return posts.find((post) => post.slug === slug);
}

export function getPost(slug: string): BlogPost | undefined {
  const meta = getPostMeta(slug);
  const body = BLOG_BODIES[slug];
  return meta && body !== undefined ? { ...meta, body } : undefined;
}

/**
 * Drafts are listed on `/blog` only under `next dev`, so the owner can find
 * them while reviewing; a production build never lists (or links) a draft.
 */
export function showDraftsOnIndex(env: string | undefined = process.env.NODE_ENV): boolean {
  return env === "development";
}

/** Newest first by `publishedAt`, then by slug for a stable order. */
export function sortPosts<T extends BlogPostMeta>(posts: readonly T[]): T[] {
  return [...posts].sort(
    (a, b) => b.publishedAt.localeCompare(a.publishedAt) || a.slug.localeCompare(b.slug),
  );
}

/**
 * Related posts for `post`. A published post shows only published ones (it
 * must never link a noindex draft); a draft may show drafts.
 */
export function relatedPosts(
  post: BlogPostMeta,
  posts: readonly BlogPostMeta[] = BLOG_POSTS,
): BlogPostMeta[] {
  return post.related.flatMap((slug) => {
    const related = getPostMeta(slug, posts);
    if (!related || related.slug === post.slug) return [];
    if (isPublished(post) && !isPublished(related)) return [];
    return [related];
  });
}

/** `2026-10-15` → `15/10/2026` (dates are calendar dates, no timezone shift). */
export function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-");
  return `${day}/${month}/${year}`;
}
