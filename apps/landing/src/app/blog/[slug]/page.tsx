import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  countWords,
  MarkdownBlocks,
  parseMarkdown,
  readingMinutes,
  tableOfContents,
} from "../../../components/blog/markdown";
import { PostMetaLine } from "../../../components/blog/post-meta-line";
import { LandingHeader } from "../../../components/landing-header";
import { SiteFooter } from "../../../components/site-footer";
import { BLOG_POSTS, getPost, getPostMeta, isPublished, relatedPosts } from "../../../content/blog";
import {
  articleSchema,
  breadcrumbSchema,
  breadcrumbTrail,
  buildMetadata,
  faqPageSchema,
  JsonLd,
} from "../../../lib/seo";
import { blogPostPath } from "../../../lib/seo/routes/blog";

/**
 * `/blog/<slug>` — one post (D43.7). Every post is prerendered, drafts too (so
 * the owner can review them and `check:seo` covers them); a draft is noindex
 * through the route registry and shows a banner. Unknown slugs are 404.
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
    publishedTime: post.publishedAt,
    modifiedTime: post.updatedAt,
    authors: [post.author],
  });
}

/** Links to `/blog/<slug>` of a draft are rendered as plain text on a published post. */
function linkFilterFor(published: boolean) {
  if (!published) return () => true;
  return (href: string) => {
    const match = /^\/blog\/([a-z0-9-]+)/.exec(href);
    if (!match) return true;
    const target = getPostMeta(match[1]!);
    return target ? isPublished(target) : false;
  };
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
  const trail = breadcrumbTrail(path);
  const faq = post.faq ?? [];

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
          }),
          ...(faq.length > 0 ? [faqPageSchema(faq)] : []),
        ]}
      />
      <LandingHeader />
      <main className="lp-main">
        <article className="lp-blog">
          <nav aria-label="Breadcrumb" className="lp-blog__breadcrumb">
            <ol>
              {trail.map((item, index) => (
                <li key={item.path}>
                  {index < trail.length - 1 ? (
                    <Link href={item.path}>{item.path === "/" ? "Trang chủ" : item.name}</Link>
                  ) : (
                    <span aria-current="page">{item.name}</span>
                  )}
                </li>
              ))}
            </ol>
          </nav>

          {published ? null : (
            <p className="lp-blog__draft" role="note">
              Bản nháp đang chờ duyệt: trang này không được lập chỉ mục và không có trong sitemap.
            </p>
          )}

          <header className="lp-blog__header">
            <h1 className="lp-blog__title">{post.title}</h1>
            <PostMetaLine
              author={post.author}
              minutes={minutes}
              publishedAt={post.publishedAt}
              updatedAt={post.updatedAt}
            />
            <p className="lp-blog__lead">{post.excerpt}</p>
          </header>

          {toc.length > 0 ? (
            <nav aria-label="Mục lục" className="lp-blog__toc">
              <p className="lp-blog__toc-label">Mục lục</p>
              <ol>
                {toc.map((entry) => (
                  <li key={entry.id}>
                    <a href={`#${entry.id}`}>{entry.text}</a>
                  </li>
                ))}
              </ol>
            </nav>
          ) : null}

          <div className="lp-blog__body">
            <MarkdownBlocks blocks={blocks} isLinkable={linkFilterFor(published)} />
          </div>

          {faq.length > 0 ? (
            <section aria-labelledby="cau-hoi-thuong-gap" className="lp-blog__section">
              <h2 className="lp-blog__h2" id="cau-hoi-thuong-gap">
                Câu hỏi thường gặp
              </h2>
              {faq.map((item) => (
                <div className="lp-blog__faq-item" key={item.question}>
                  <h3 className="lp-blog__h3">{item.question}</h3>
                  <p>{item.answer}</p>
                </div>
              ))}
            </section>
          ) : null}

          {post.sources.length > 0 ? (
            <section aria-labelledby="nguon-tham-khao" className="lp-blog__section lp-blog__sources">
              <h2 className="lp-blog__h2" id="nguon-tham-khao">
                Nguồn tham khảo
              </h2>
              <ul>
                {post.sources.map((source) => (
                  <li key={source.url + source.title}>
                    <a className="lp-blog__link" href={source.url} rel="noopener noreferrer">
                      {source.title}
                    </a>
                    {source.note ? <span className="lp-blog__source-note"> ({source.note})</span> : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {related.length > 0 ? (
            <section aria-labelledby="bai-viet-lien-quan" className="lp-blog__section">
              <h2 className="lp-blog__h2" id="bai-viet-lien-quan">
                Bài viết liên quan
              </h2>
              <ul className="lp-blog__related">
                {related.map((item) => (
                  <li key={item.slug}>
                    <Link className="lp-blog__link" href={blogPostPath(item.slug)}>
                      {item.title}
                    </Link>
                    <p>{item.excerpt}</p>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </article>
      </main>
      <SiteFooter />
    </>
  );
}
