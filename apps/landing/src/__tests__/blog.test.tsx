import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import BlogPostPage, { generateMetadata, generateStaticParams } from "../app/blog/[slug]/page";
import BlogIndexPage from "../app/blog/page";
import sitemap from "../app/sitemap";
import { countWords, markdownLinks, parseMarkdown, slugify, tableOfContents } from "../components/blog/markdown";
import { BLOG_POSTS, getPost, relatedPosts, showDraftsOnIndex } from "../content/blog";
import type { BlogPostMeta } from "../content/blog/types";
import { absoluteUrl, getRoute, metadataForRoute, SITE_ROUTES, sitemapEntries } from "../lib/seo";
import { blogPostPath, buildBlogRoutes } from "../lib/seo/routes/blog";

/** P33-C product pages every pillar post links to (all registered since integration). */
const PRODUCT_PAGES = new Set([
  "/san-pham/phan-tich-shop",
  "/san-pham/de-xuat-va-thuc-thi",
  "/san-pham/do-luong-gmv",
  "/ket-noi/tiktok-shop",
]);

const fixture = (slug: string, status: BlogPostMeta["status"]): BlogPostMeta => ({
  slug,
  status,
  title: `Tiêu đề ${slug}`,
  seoTitle: `Tiêu đề ${slug} | Juli AI`,
  description: `Mô tả đủ dài cho bài ${slug}, dùng trong kiểm thử sitemap và robots của blog.`,
  excerpt: "Tóm tắt.",
  breadcrumbName: slug,
  publishedAt: "2026-10-20",
  updatedAt: "2026-10-21",
  author: "Đội ngũ Juli AI",
  related: [],
  sources: [],
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("blog drafts vs published posts (AC-33.8)", () => {
  const routes = buildBlogRoutes([fixture("ban-nhap", "draft"), fixture("da-dang", "published")]);
  const draft = routes.find((route) => route.path === "/blog/ban-nhap")!;
  const live = routes.find((route) => route.path === "/blog/da-dang")!;

  it("registers a draft as noindex and keeps it out of the sitemap", () => {
    expect(draft.noindex).toBe(true);
    expect(metadataForRoute(draft).robots).toEqual({ index: false, follow: true });
    const urls = sitemapEntries(routes).map((entry) => entry.url);
    expect(urls).not.toContain(absoluteUrl("/blog/ban-nhap"));
  });

  it("registers a published post as indexable, in the sitemap with its lastmod", () => {
    expect(live.noindex).toBeUndefined();
    expect(metadataForRoute(live).robots).toBeUndefined();
    expect(sitemapEntries(routes)).toContainEqual(
      expect.objectContaining({ url: absoluteUrl("/blog/da-dang"), lastModified: "2026-10-21" }),
    );
    expect(live).toMatchObject({ parent: "/blog", ogType: "article" });
  });

  it("dates the /blog index by its newest published post", () => {
    expect(routes[0]).toMatchObject({ path: "/blog", lastModified: "2026-10-21" });
    expect(routes[0]!.noindex).toBeUndefined();
  });

  it("never relates a published post to a draft", () => {
    const posts = [
      { ...fixture("a", "published"), related: ["b", "c"] },
      fixture("b", "draft"),
      fixture("c", "published"),
    ];
    expect(relatedPosts(posts[0]!, posts).map((post) => post.slug)).toEqual(["c"]);
    expect(relatedPosts({ ...posts[1]!, related: ["a"] }, posts).map((post) => post.slug)).toEqual(["a"]);
  });

  it("the three pillar drafts are registered, noindex, and absent from the real sitemap", () => {
    const urls = sitemap().map((entry) => entry.url);
    expect(urls).toContain(absoluteUrl("/blog"));
    for (const post of BLOG_POSTS) {
      const route = getRoute(blogPostPath(post.slug));
      expect(route.noindex, post.slug).toBe(post.status !== "published");
      expect(urls.includes(absoluteUrl(route.path)), post.slug).toBe(post.status === "published");
    }
  });
});

describe("/blog index", () => {
  it("lists drafts only under next dev", () => {
    expect(showDraftsOnIndex("development")).toBe(true);
    expect(showDraftsOnIndex("production")).toBe(false);
    expect(showDraftsOnIndex("test")).toBe(false);
  });

  it("does not link any draft in a production build", () => {
    vi.stubEnv("NODE_ENV", "production");
    const { container } = render(<BlogIndexPage />);
    const hrefs = [...container.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    for (const post of BLOG_POSTS.filter((p) => p.status !== "published")) {
      expect(hrefs).not.toContain(blogPostPath(post.slug));
    }
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("lists drafts under 'Bản nháp chờ duyệt' in development", () => {
    vi.stubEnv("NODE_ENV", "development");
    render(<BlogIndexPage />);
    const drafts = screen.getByRole("heading", { name: /Bản nháp chờ duyệt/ }).closest("section")!;
    for (const post of BLOG_POSTS.filter((p) => p.status === "draft")) {
      expect(within(drafts).getByRole("link", { name: post.title })).toHaveAttribute(
        "href",
        blogPostPath(post.slug),
      );
    }
  });
});

describe("post page", () => {
  it("prerenders every post", () => {
    expect(generateStaticParams()).toEqual(BLOG_POSTS.map((post) => ({ slug: post.slug })));
  });

  it("renders title, author, dates, TOC from the H2s, FAQ, sources and the draft banner", async () => {
    const post = BLOG_POSTS[0]!;
    render(await BlogPostPage({ params: Promise.resolve({ slug: post.slug }) }));

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(post.title);
    expect(screen.getAllByText(post.author).length).toBeGreaterThan(0);
    expect(document.querySelector(`time[datetime="${post.publishedAt}"]`)).not.toBeNull();

    const toc = screen.getByRole("navigation", { name: "Mục lục" });
    const bodyH2 = tableOfContents(parseMarkdown(getPost(post.slug)!.body));
    expect(within(toc).getAllByRole("link")).toHaveLength(bodyH2.length);
    for (const entry of bodyH2) {
      expect(document.getElementById(entry.id)).not.toBeNull();
    }

    for (const item of post.faq ?? []) {
      expect(screen.getByRole("heading", { level: 3, name: item.question })).toBeInTheDocument();
    }
    expect(screen.getByRole("note")).toHaveTextContent(/Bản nháp/);

    const jsonLd = [...document.querySelectorAll('script[type="application/ld+json"]')]
      .map((script) => JSON.stringify(JSON.parse(script.textContent ?? "")))
      .join(" ");
    expect(jsonLd).toContain('"@type":"Article"');
    expect(jsonLd).toContain('"@type":"BreadcrumbList"');
    expect(jsonLd).toContain('"@type":"FAQPage"');
  });

  it("sets article metadata with published/modified times and noindex for a draft", async () => {
    const post = BLOG_POSTS[0]!;
    const metadata = await generateMetadata({ params: Promise.resolve({ slug: post.slug }) });
    expect(metadata.openGraph).toMatchObject({
      type: "article",
      publishedTime: post.publishedAt,
      modifiedTime: post.updatedAt,
      authors: [post.author],
    });
    expect(metadata.robots).toEqual({ index: false, follow: true });
  });
});

describe("pillar posts content (D43.7)", () => {
  for (const meta of BLOG_POSTS) {
    const post = getPost(meta.slug)!;

    it(`${meta.slug}: 3,000+ words, H2 → H3 only, unique headings`, () => {
      expect(countWords(post.body)).toBeGreaterThanOrEqual(3000);
      const blocks = parseMarkdown(post.body);
      expect(blocks[0]?.kind).not.toBe("h3");
      const ids = blocks.flatMap((block) => ("id" in block ? [block.id] : []));
      expect(new Set(ids).size).toBe(ids.length);
      expect(tableOfContents(blocks).length).toBeGreaterThanOrEqual(5);
    });

    it(`${meta.slug}: internal links resolve, and it links the product pages`, () => {
      const internal = markdownLinks(post.body).filter((href) => href.startsWith("/"));
      const registered = new Set(SITE_ROUTES.map((route) => route.path));
      for (const href of internal) {
        expect(registered.has(href), href).toBe(true);
      }
      for (const page of ["/san-pham", ...PRODUCT_PAGES]) {
        expect(internal, page).toContain(page);
      }
    });

    it(`${meta.slug}: title and description fit the registry rules`, () => {
      expect(meta.seoTitle.length).toBeLessThanOrEqual(60);
      expect(meta.description.length).toBeGreaterThanOrEqual(70);
      expect(meta.description.length).toBeLessThanOrEqual(155);
      expect(meta.updatedAt >= meta.publishedAt).toBe(true);
    });
  }
});

describe("markdown subset", () => {
  it("slugifies Vietnamese headings", () => {
    expect(slugify("Đọc chỉ số theo năm kênh")).toBe("doc-chi-so-theo-nam-kenh");
    expect(slugify("CTOR thấp: trước giỏ hay sau giỏ")).toBe("ctor-thap-truoc-gio-hay-sau-gio");
  });

  it("parses headings, lists, callouts and tables", () => {
    const blocks = parseMarkdown(
      "## A\n\nđoạn [x](/san-pham)\n\n- một\n- hai\n\n> ghi chú\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n### B",
    );
    expect(blocks.map((block) => block.kind)).toEqual(["h2", "p", "ul", "callout", "table", "h3"]);
  });

  it("rejects an H1 or H4 in a body", () => {
    expect(() => parseMarkdown("# H1")).toThrow();
    expect(() => parseMarkdown("#### H4")).toThrow();
  });
});
