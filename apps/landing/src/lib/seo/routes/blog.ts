import { BLOG_POSTS } from "../../../content/blog/posts";
import type { BlogPostMeta } from "../../../content/blog/types";
import type { SiteRoute } from "./types";

export const BLOG_INDEX_PATH = "/blog";

/** Last change to the index page's own copy (its lastmod is the later of this and the newest published post). */
const INDEX_LAST_MODIFIED = "2026-10-15";

export function blogPostPath(slug: string): string {
  return `${BLOG_INDEX_PATH}/${slug}`;
}

/**
 * The `/blog` index plus one route per post (D43.7). Owner: P33-D. A post whose
 * `status` is not `"published"` is registered `noindex`: rendered for review
 * and checked by `check:seo`, but robots `noindex` and out of the sitemap
 * (src/content/blog/README.md explains how the owner approves a post).
 */
export function buildBlogRoutes(posts: readonly BlogPostMeta[]): SiteRoute[] {
  const publishedDates = posts.filter((post) => post.status === "published").map((post) => post.updatedAt);
  const indexLastModified = [INDEX_LAST_MODIFIED, ...publishedDates].sort().at(-1)!;
  return [
    {
      path: BLOG_INDEX_PATH,
      title: "Blog kiến thức bán hàng TikTok Shop | Juli AI",
      description:
        "Bài viết chuyên sâu cho nhà bán TikTok Shop: đọc đúng Lượt hiển thị, CTR, CTOR, AOV, tối ưu thẻ sản phẩm và chọn công cụ phù hợp.",
      lastModified: indexLastModified,
      breadcrumbName: "Blog",
      changeFrequency: "weekly",
      priority: 0.6,
    },
    ...posts.map(
      (post): SiteRoute => ({
        path: blogPostPath(post.slug),
        title: post.seoTitle,
        description: post.description,
        lastModified: post.updatedAt,
        breadcrumbName: post.breadcrumbName,
        parent: BLOG_INDEX_PATH,
        changeFrequency: "monthly",
        priority: 0.6,
        ogType: "article",
        ...(post.status === "published" ? {} : { noindex: true }),
      }),
    ),
  ];
}

export const BLOG_ROUTES: readonly SiteRoute[] = buildBlogRoutes(BLOG_POSTS);
