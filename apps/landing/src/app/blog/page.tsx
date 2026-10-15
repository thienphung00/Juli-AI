import { CategoryFilter } from "../../components/blog/category-filter";
import { countWords, readingMinutes } from "../../components/blog/markdown";
import { PostCard } from "../../components/blog/post-card";
import { Heading } from "../../components/ui";
import { SiteFooter } from "../../components/ui/site-footer";
import { SiteHeader } from "../../components/ui/site-header";
import {
  BLOG_CATEGORIES,
  BLOG_CATEGORY_ORDER,
  BLOG_POSTS,
  type BlogPostMeta,
  getPost,
  isPublished,
  showDraftsOnIndex,
  sortPosts,
} from "../../content/blog";
import { breadcrumbSchema, buildMetadata, JsonLd } from "../../lib/seo";

/**
 * `/blog` — the post list (D43.7, redesigned to Blog.dc.html in P34-D): H1 +
 * lead + topic pills, one featured card, then a 3-up grid. Production lists
 * published posts only; `next dev` also lists drafts (badge "Bản nháp") so the
 * owner can review them.
 */
export const metadata = buildMetadata("/blog");

function minutesFor(post: BlogPostMeta): number {
  return readingMinutes(countWords(getPost(post.slug)?.body ?? ""));
}

export default function BlogIndexPage() {
  const posts = sortPosts(BLOG_POSTS).filter((post) => isPublished(post) || showDraftsOnIndex());
  const [featured, ...rest] = posts;
  const options = BLOG_CATEGORY_ORDER.flatMap((key) => {
    const count = posts.filter((post) => post.category === key).length;
    return count > 0 ? [{ key, label: BLOG_CATEGORIES[key].label, count }] : [];
  });

  return (
    <>
      <JsonLd data={breadcrumbSchema("/blog")} />
      <SiteHeader />
      <main className="lp-blog-main">
        <CategoryFilter
          intro={
            <>
              <Heading className="lp-blog-index__h1" level={1} size="page">
                Blog Juli
              </Heading>
              <p className="lp-blog-index__lead">
                Hướng dẫn đọc chỉ số, tối ưu thẻ sản phẩm và vận hành TikTok Shop, viết từ dữ liệu và tài
                liệu chính thức của TikTok.
              </p>
            </>
          }
          options={options}
          total={posts.length}
        >
          {featured ? (
            <>
              <section aria-label="Bài nổi bật" className="ui-container lp-blog-index__featured">
                <PostCard minutes={minutesFor(featured)} post={featured} priority variant="featured" />
              </section>
              {rest.length > 0 ? (
                <section aria-label="Bài viết" className="ui-container lp-blog-index__grid">
                  {rest.map((post) => (
                    <PostCard key={post.slug} minutes={minutesFor(post)} post={post} />
                  ))}
                </section>
              ) : null}
            </>
          ) : (
            <div className="ui-container">
              <p className="lp-blog-index__empty">
                Những bài viết đầu tiên đang được biên tập và sẽ sớm xuất hiện tại đây.
              </p>
            </div>
          )}
        </CategoryFilter>
      </main>
      <SiteFooter />
    </>
  );
}
