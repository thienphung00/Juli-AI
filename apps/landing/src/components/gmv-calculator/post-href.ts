import { getPostMeta, isPublished } from "../../content/blog";
import { GMV_POST_SLUG } from "./content";

/**
 * The "GMV là gì" post, linked from the GMV tool only once the owner publishes
 * it: an indexable page never links a noindex draft (check:seo). While it is a
 * draft the link text renders as plain text. Server-only use (it reads the blog
 * registry, which the client bundle should not carry).
 */
export function gmvPostHref(posts?: Parameters<typeof getPostMeta>[1]): string | null {
  const post = getPostMeta(GMV_POST_SLUG, posts);
  return post && isPublished(post) ? `/blog/${post.slug}` : null;
}
