import Link from "next/link";

import { BLOG_CATEGORIES, type BlogPostMeta, formatDate, isPublished } from "../../content/blog";
import { blogPostPath } from "../../lib/seo/routes/blog";
import { Picture } from "../picture";

export interface PostCardProps {
  post: BlogPostMeta;
  /** Reading time in minutes (from the body word count). */
  minutes: number;
  /** `featured` = the wide card at the top of `/blog`; `grid` = the 3-up cards. */
  variant?: "featured" | "grid";
  headingLevel?: 2 | 3;
  /** LCP image (the featured cover). */
  priority?: boolean;
}

/** "Chỉ số · 18 phút đọc" in the category's text colour. */
export function CategoryLine({ post, minutes, className }: { post: BlogPostMeta; minutes: number; className?: string }) {
  return (
    <p className={`lp-cat lp-cat--${post.category}${className ? ` ${className}` : ""}`}>
      {BLOG_CATEGORIES[post.category].label} · {minutes} phút đọc
    </p>
  );
}

/**
 * One post on `/blog` and in "Bài viết liên quan" (Blog.dc.html). The title is
 * the only link; it stretches over the whole card, so the card is one target
 * with a short accessible name. The cover is decorative here (alt="").
 */
export function PostCard({ post, minutes, variant = "grid", headingLevel = 2, priority = false }: PostCardProps) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  const featured = variant === "featured";
  return (
    <article className={`lp-post-card lp-post-card--${variant}`} data-category={post.category}>
      <div className="lp-post-card__cover">
        <Picture
          alt=""
          priority={priority}
          sizes={
            featured
              ? "(min-width: 1200px) 640px, (min-width: 960px) 55vw, 100vw"
              : "(min-width: 1200px) 370px, (min-width: 700px) 45vw, 100vw"
          }
          variants={post.cover.variants}
        />
      </div>
      <div className="lp-post-card__text">
        <CategoryLine minutes={minutes} post={post} />
        <Heading className="lp-post-card__title">
          <Link className="lp-post-card__link" href={blogPostPath(post.slug)}>
            {post.title}
          </Link>
        </Heading>
        <p className="lp-post-card__excerpt">{post.excerpt}</p>
        <p className="lp-post-card__meta">
          {post.author} · <time dateTime={post.publishedAt}>{formatDate(post.publishedAt)}</time>
          {isPublished(post) ? null : <span className="lp-draft-badge">Bản nháp</span>}
        </p>
      </div>
    </article>
  );
}
