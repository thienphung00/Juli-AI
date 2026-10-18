import type { Metadata } from "next";
import { notFound } from "next/navigation";

import {
  countWords,
  MarkdownBlocks,
  parseMarkdown,
  readingMinutes,
  tableOfContents,
} from "../../../components/blog/markdown";
import { CategoryLine, PostCard } from "../../../components/blog/post-card";
import { PostMetaLine } from "../../../components/blog/post-meta-line";
import { Picture } from "../../../components/picture";
import { Breadcrumb, FaqList, Heading, LinkButton, Section, TocNav } from "../../../components/ui";
import { SiteFooter } from "../../../components/ui/site-footer";
import { SiteHeader } from "../../../components/ui/site-header";
import {
  BLOG_POSTS,
  blogTier,
  type BlogSource,
  formatDate,
  getPost,
  getPostMeta,
  guideFor,
  isCompetitorUrl,
  isPublished,
  relatedPosts,
} from "../../../content/blog";
import {
  articleSchema,
  breadcrumbSchema,
  buildMetadata,
  faqPageSchema,
  JsonLd,
} from "../../../lib/seo";
import { BLOG_INDEX_PATH, blogPostPath } from "../../../lib/seo/routes/blog";
import { DEMO_URL, FREE_TOOLS, SIGNUP_URL, TRIAL_CTA_LABEL } from "../../../lib/site";

/**
 * `/blog/<slug>` — one post (D43.7; layout P34-D, D44). Every post is
 * prerendered, drafts too (so the owner can review them and `check:seo` covers
 * them); a draft is noindex through the route registry and shows a banner.
 * Unknown slugs are 404.
 */
export const dynamicParams = false;

export function generateStaticParams(): { slug: string }[] {
  return BLOG_POSTS.map((post) => ({ slug: post.slug }));
}

interface PostPageProps {
  params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: PostPageProps): Promise<Metadata> {
  const { slug } = await params;
  const post = getPostMeta(slug);
  if (!post) return {};
  return buildMetadata(blogPostPath(post.slug), {
    ogImage: post.cover.og,
    publishedTime: post.publishedAt,
    modifiedTime: post.updatedAt,
    authors: [post.author],
  });
}

/** Links to `/blog/<slug>` of a draft are rendered as plain text on a published post. */
/**
 * Which body links render as links. A competitor / vendor domain never does
 * (D56 G2, `content/blog/competitors.ts`; `blog.test.tsx` keeps them out of the
 * bodies, this is the backstop). A published post also unlinks drafts.
 */
function linkFilterFor(published: boolean) {
  return (href: string) => {
    if (isCompetitorUrl(href)) return false;
    if (!published) return true;
    const match = /^\/blog\/([a-z0-9-]+)/.exec(href);
    if (!match) return true;
    const target = getPostMeta(match[1]!);
    return target ? isPublished(target) : false;
  };
}

/** "<note>, kiểm tra DD/MM/YYYY" for an unlinked source; the note alone for a linked one. */
function sourceNote(source: BlogSource): string {
  const checked = source.checkedAt ? `kiểm tra ${formatDate(source.checkedAt)}` : "";
  return [source.note, checked].filter(Boolean).join(", ");
}

function minutesFor(slug: string): number {
  return readingMinutes(countWords(getPost(slug)?.body ?? ""));
}

/**
 * End-of-post CTA of a reach post (D59: pain / news). Brand-neutral on purpose:
 * no "Juli", no product, sign-up or demo link; it offers the free GMV
 * calculator and the blog index instead.
 */
function ReachCta({ guidePath }: { guidePath: string | null }) {
  return (
    <Section labelledBy="blog-cta" spacing="compact" tone="dark">
      <div className="lp-post__cta" data-testid="blog-cta-tool">
        <Heading id="blog-cta" level={2} onDark size="feature">
          Tự tính GMV và tìm bước yếu nhất
        </Heading>
        <p className="lp-post__cta-lead">
          Nhập lượt hiển thị, CTR, CTOR và giá trị đơn trung bình vào công cụ tính GMV miễn phí để xem
          bước nào trong phễu đang kéo doanh thu xuống. Không cần đăng ký.
        </p>
        <div className="lp-post__cta-actions">
          <LinkButton data-testid="blog-cta-calculator" href={FREE_TOOLS.gmvCalculator.href} variant="on-dark">
            Mở công cụ tính GMV
          </LinkButton>
          <LinkButton data-testid="blog-cta-index" href={BLOG_INDEX_PATH} variant="on-dark-secondary">
            Đọc thêm bài viết
          </LinkButton>
        </div>
        {guidePath ? (
          <p className="lp-post__cta-guide">
            <a data-testid="blog-cta-guide" href={guidePath}>
              Đọc hướng dẫn liên quan
            </a>
          </p>
        ) : null}
      </div>
    </Section>
  );
}

/** End-of-post CTA of a conversion post (D59: pillar / comparison / guide): Juli trial + demo. */
function ConversionCta() {
  return (
    <Section labelledBy="blog-cta" spacing="compact" tone="dark">
      <div className="lp-post__cta">
        <Heading id="blog-cta" level={2} onDark size="feature">
          Để Juli đọc các chỉ số này cho shop của bạn mỗi ngày.
        </Heading>
        <p className="lp-post__cta-lead">
          Juli phân tích GMV theo từng luồng truy cập, đề xuất việc nên làm kèm lý do và chỉ thực hiện
          khi bạn phê duyệt.
        </p>
        <div className="lp-post__cta-actions">
          <LinkButton data-testid="blog-cta-trial" href={SIGNUP_URL} variant="on-dark">
            {TRIAL_CTA_LABEL}
          </LinkButton>
          <LinkButton data-testid="blog-cta-demo" href={DEMO_URL} variant="on-dark-secondary">
            Xem demo với dữ liệu mẫu
          </LinkButton>
        </div>
      </div>
    </Section>
  );
}

export default async function BlogPostPage({ params }: PostPageProps) {
  const { slug } = await params;
  const post = getPost(slug);
  if (!post) notFound();

  const path = blogPostPath(post.slug);
  const published = isPublished(post);
  const blocks = parseMarkdown(post.body);
  const toc = tableOfContents(blocks);
  const minutes = readingMinutes(countWords(post.body));
  const related = relatedPosts(post);
  const faq = post.faq ?? [];
  const tocItems = [
    ...toc.map((entry) => ({ id: entry.id, label: entry.text })),
    ...(faq.length > 0 ? [{ id: "cau-hoi-thuong-gap", label: "Câu hỏi thường gặp" }] : []),
  ];

  return (
    <>
      <JsonLd
        data={[
          breadcrumbSchema(path),
          articleSchema({
            path,
            headline: post.title,
            description: post.description,
            datePublished: post.publishedAt,
            dateModified: post.updatedAt,
            image: [post.cover.og.url, post.cover.variants.at(-1)!.webp],
          }),
          ...(faq.length > 0 ? [faqPageSchema(faq)] : []),
        ]}
      />
      <SiteHeader />
      <main className="lp-blog-main">
        <article className="lp-post">
          <header className="ui-container lp-post__header">
            <Breadcrumb current={post.breadcrumbName} items={[{ href: BLOG_INDEX_PATH, label: "Blog" }]} />
            {published ? null : (
              <p className="lp-post__draft" role="note">
                Bản nháp đang chờ duyệt: trang này không được lập chỉ mục và không có trong sitemap.
              </p>
            )}
            <CategoryLine minutes={minutes} post={post} />
            <Heading className="lp-post__title" level={1} size="page">
              {post.title}
            </Heading>
            <p className="lp-post__standfirst">{post.excerpt}</p>
            <PostMetaLine
              author={post.author}
              minutes={minutes}
              publishedAt={post.publishedAt}
              updatedAt={post.updatedAt}
            />
            <div className="lp-post__cover">
              <Picture
                alt={post.cover.alt}
                priority
                sizes="(min-width: 1200px) 1152px, 100vw"
                variants={post.cover.variants}
              />
            </div>
          </header>

          <div className="ui-container">
            <div className="ui-toc-layout lp-post__layout">
              {tocItems.length > 0 ? <TocNav items={tocItems} title="Mục lục" /> : <div />}
              <div className="lp-post__column">
                <div className="lp-prose">
                  <MarkdownBlocks blocks={blocks} isLinkable={linkFilterFor(published)} />
                </div>

                {faq.length > 0 ? (
                  <section aria-labelledby="cau-hoi-thuong-gap" className="lp-post__section">
                    <h2 className="lp-blog__h2" id="cau-hoi-thuong-gap">
                      Câu hỏi thường gặp
                    </h2>
                    <FaqList items={faq} />
                  </section>
                ) : null}

                {post.sources.length > 0 ? (
                  <section aria-labelledby="nguon-tham-khao" className="lp-post__section lp-post__sources">
                    <h2 className="lp-blog__h2" id="nguon-tham-khao">
                      Nguồn tham khảo
                    </h2>
                    <ul>
                      {post.sources.map((source) => (
                        <li key={(source.url ?? source.checkedAt) + source.title}>
                          {source.url && !isCompetitorUrl(source.url) ? (
                            <a className="lp-blog__link" href={source.url} rel="noopener noreferrer">
                              {source.title}
                            </a>
                          ) : (
                            // D56 G2: a competitor / vendor page is cited by name and check date, no link.
                            <span className="lp-post__source-name">{source.title}</span>
                          )}
                          {sourceNote(source) ? <span className="lp-post__source-note"> ({sourceNote(source)})</span> : null}
                        </li>
                      ))}
                    </ul>
                  </section>
                ) : null}
              </div>
            </div>
          </div>
        </article>

        {related.length > 0 ? (
          <section aria-labelledby="bai-viet-lien-quan" className="ui-container lp-post__related">
            <h2 className="lp-blog__h2" id="bai-viet-lien-quan">
              Bài viết liên quan
            </h2>
            <div className="lp-blog-index__grid lp-post__related-grid">
              {related.map((item) => (
                <PostCard headingLevel={3} key={item.slug} minutes={minutesFor(item.slug)} post={item} />
              ))}
            </div>
          </section>
        ) : null}

        {blogTier(post) === "reach" ? (
          <ReachCta guidePath={guideFor(post) ? blogPostPath(post.guide!) : null} />
        ) : (
          <ConversionCta />
        )}
      </main>
      <SiteFooter />
    </>
  );
}
