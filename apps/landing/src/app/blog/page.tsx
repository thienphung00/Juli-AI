import Link from "next/link";

import { PostMetaLine } from "../../components/blog/post-meta-line";
import { countWords, readingMinutes } from "../../components/blog/markdown";
import { LandingHeader } from "../../components/landing-header";
import { SiteFooter } from "../../components/site-footer";
import {
  BLOG_POSTS,
  type BlogPostMeta,
  getPost,
  isPublished,
  showDraftsOnIndex,
  sortPosts,
} from "../../content/blog";
import { breadcrumbSchema, buildMetadata, JsonLd } from "../../lib/seo";
import { blogPostPath } from "../../lib/seo/routes/blog";

/**
 * `/blog` — the post list (D43.7). Production lists published posts only;
 * `next dev` also lists drafts under "Bản nháp chờ duyệt" for the owner.
 */
export const metadata = buildMetadata("/blog");

const PRODUCT_LINKS = [
  { href: "/san-pham/phan-tich-shop", label: "Phân tích shop theo luồng truy cập" },
  { href: "/san-pham/de-xuat-va-thuc-thi", label: "Đề xuất và thực thi khi bạn phê duyệt" },
  { href: "/san-pham/do-luong-gmv", label: "Đo lường tác động lên GMV" },
  { href: "/ket-noi/tiktok-shop", label: "Kết nối TikTok Shop" },
  { href: "/san-pham", label: "Tổng quan sản phẩm Juli AI" },
] as const;

function minutesFor(post: BlogPostMeta): number {
  return readingMinutes(countWords(getPost(post.slug)?.body ?? ""));
}

function PostSummary({ post, headingLevel }: { post: BlogPostMeta; headingLevel: 2 | 3 }) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <article className="lp-blog-index__item">
      <Heading className="lp-blog-index__title">
        <Link href={blogPostPath(post.slug)}>{post.title}</Link>
      </Heading>
      <PostMetaLine minutes={minutesFor(post)} publishedAt={post.publishedAt} updatedAt={post.updatedAt} />
      <p className="lp-blog-index__excerpt">{post.excerpt}</p>
    </article>
  );
}

export default function BlogIndexPage() {
  const posts = sortPosts(BLOG_POSTS);
  const published = posts.filter(isPublished);
  const drafts = showDraftsOnIndex() ? posts.filter((post) => !isPublished(post)) : [];

  return (
    <>
      <JsonLd data={breadcrumbSchema("/blog")} />
      <LandingHeader />
      <main className="lp-main">
        <section aria-labelledby="blog-heading" className="lp-page-hero">
          <p className="lp-page-hero__eyebrow">Blog</p>
          <h1 className="lp-page-hero__heading" id="blog-heading">
            Kiến thức bán hàng TikTok Shop
          </h1>
          <p className="lp-page-hero__lead">
            Bài viết chuyên sâu về cách đọc chỉ số, tối ưu thẻ sản phẩm và vận hành shop TikTok, dùng
            đúng tên và định nghĩa chỉ số trên Trung tâm nhà bán hàng.
          </p>
        </section>

        <section aria-label="Bài viết" className="lp-blog-index">
          {published.length > 0 ? (
            published.map((post) => <PostSummary headingLevel={2} key={post.slug} post={post} />)
          ) : (
            <p className="lp-blog-index__empty">
              Những bài viết đầu tiên đang được biên tập và sẽ sớm xuất hiện tại đây.
            </p>
          )}
        </section>

        {drafts.length > 0 ? (
          <section aria-labelledby="blog-drafts-heading" className="lp-blog-index lp-blog-index--drafts">
            <h2 className="lp-blog-index__section-heading" id="blog-drafts-heading">
              Bản nháp chờ duyệt (chỉ hiển thị khi chạy dev)
            </h2>
            {drafts.map((post) => (
              <PostSummary headingLevel={3} key={post.slug} post={post} />
            ))}
          </section>
        ) : null}

        <section aria-labelledby="blog-product-heading" className="lp-page-section">
          <h2 className="lp-page-section__heading" id="blog-product-heading">
            Juli AI làm gì cho shop của bạn
          </h2>
          <ul className="lp-blog-index__links">
            {PRODUCT_LINKS.map((link) => (
              <li key={link.href}>
                <Link className="lp-blog__link" href={link.href}>
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
