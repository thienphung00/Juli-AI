import { existsSync } from "node:fs";
import { join } from "node:path";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import BlogPostPage, { generateMetadata, generateStaticParams } from "../app/blog/[slug]/page";
import BlogIndexPage from "../app/blog/page";
import sitemap from "../app/sitemap";
import { countWords, markdownLinks, parseMarkdown, slugify, tableOfContents } from "../components/blog/markdown";
import { BLOG_CATEGORIES, BLOG_POSTS, blogCover, getPost, relatedPosts, showDraftsOnIndex } from "../content/blog";
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
  category: "guide",
  cover: blogCover("fixture-v1", "Minh hoạ"),
  related: [],
  sources: [],
});

const PUBLIC_DIR = join(process.cwd(), "public");

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

  it("lists drafts in development as cards with a 'Bản nháp' badge: featured + grid", () => {
    vi.stubEnv("NODE_ENV", "development");
    render(<BlogIndexPage />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    const featured = screen.getByRole("region", { name: "Bài nổi bật" });
    const grid = screen.getByRole("region", { name: "Bài viết" });
    expect(within(featured).getAllByRole("article")).toHaveLength(1);
    expect(within(grid).getAllByRole("article")).toHaveLength(BLOG_POSTS.length - 1);
    for (const post of BLOG_POSTS) {
      const link = screen.getByRole("link", { name: post.title });
      expect(link).toHaveAttribute("href", blogPostPath(post.slug));
      const card = link.closest("article")!;
      expect(card).toHaveAttribute("data-category", post.category);
      expect(card.querySelector("img")).toHaveAttribute("alt", "");
      expect(within(card).getByText(new RegExp(`^${BLOG_CATEGORIES[post.category].label} · \\d+ phút đọc$`))).toBeInTheDocument();
      if (post.status === "draft") expect(within(card).getByText("Bản nháp")).toBeInTheDocument();
    }
  });

  it("filters by topic with toggle buttons (aria-pressed)", () => {
    vi.stubEnv("NODE_ENV", "development");
    const { container } = render(<BlogIndexPage />);
    const group = screen.getByRole("group", { name: "Chủ đề" });
    const all = within(group).getByRole("button", { name: "Tất cả" });
    expect(all).toHaveAttribute("aria-pressed", "true");
    const tools = within(group).getByRole("button", { name: BLOG_CATEGORIES.tools.label });
    fireEvent.click(tools);
    expect(tools).toHaveAttribute("aria-pressed", "true");
    expect(all).toHaveAttribute("aria-pressed", "false");
    expect(container.querySelector(".lp-blog-index")).toHaveAttribute("data-filter", "tools");
    const count = BLOG_POSTS.filter((post) => post.category === "tools").length;
    expect(screen.getByText(`Đang hiện ${count} bài viết`)).toBeInTheDocument();
  });

  it("shows an empty state and no topic pills when nothing is published (production)", () => {
    vi.stubEnv("NODE_ENV", "production");
    render(<BlogIndexPage />);
    if (BLOG_POSTS.some((post) => post.status === "published")) return;
    expect(screen.getByText(/đang được biên tập/)).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Chủ đề" })).toBeNull();
  });
});

describe("covers (D44.3, AC-34.4)", () => {
  for (const post of BLOG_POSTS) {
    it(`${post.slug}: has a category, a cover with alt text and files on disk, and an OG image`, () => {
      expect(Object.keys(BLOG_CATEGORIES)).toContain(post.category);
      expect(post.cover.alt.length).toBeGreaterThan(10);
      expect(post.cover.variants.map((v) => v.width)).toEqual([600, 1200]);
      for (const variant of post.cover.variants) {
        expect(variant.height).toBe(Math.round((variant.width * 9) / 16));
        for (const file of [variant.avif!, variant.webp]) {
          expect(file).toMatch(/^\/media\/blog-[a-z0-9-]+-v\d+-\d+\.(avif|webp)$/);
          expect(existsSync(join(PUBLIC_DIR, file)), file).toBe(true);
        }
      }
      expect(post.cover.og).toMatchObject({ width: 1200, height: 630, alt: post.cover.alt });
      expect(existsSync(join(PUBLIC_DIR, post.cover.og.url)), post.cover.og.url).toBe(true);
    });
  }

  it("every post has its own cover", () => {
    const urls = BLOG_POSTS.map((post) => post.cover.og.url);
    expect(new Set(urls).size).toBe(urls.length);
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
    // TocNav renders the list twice (sticky desktop list + mobile disclosure); + 1 for the FAQ.
    const tocTargets = bodyH2.length + (post.faq?.length ? 1 : 0);
    expect(within(toc).getAllByRole("link", { hidden: true })).toHaveLength(tocTargets * 2);
    for (const entry of bodyH2) {
      expect(document.getElementById(entry.id)).not.toBeNull();
    }

    const cover = screen.getByRole("img", { name: post.cover.alt });
    expect(cover).toHaveAttribute("width", "1200");
    expect(cover).toHaveAttribute("height", "675");
    expect(screen.getByText(new RegExp(`^${BLOG_CATEGORIES[post.category].label} · \\d+ phút đọc$`))).toBeInTheDocument();

    expect(screen.getByRole("heading", { level: 2, name: "Câu hỏi thường gặp" })).toBeInTheDocument();
    for (const item of post.faq ?? []) {
      expect(screen.getByText(item.question).closest("summary")).not.toBeNull();
    }
    expect(screen.getByRole("heading", { level: 2, name: "Nguồn tham khảo" })).toBeInTheDocument();
    expect(screen.getByTestId("blog-cta-trial")).toBeInTheDocument();

    // Headings never skip a level.
    const levels = [...document.querySelectorAll("h1, h2, h3, h4")].map((h) => Number(h.tagName[1]));
    levels.reduce((prev, level) => {
      expect(level - prev, `h${prev} → h${level}`).toBeLessThanOrEqual(1);
      return level;
    }, 0);
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

  it("uses each post's cover as its Open Graph and Twitter image", async () => {
    for (const post of BLOG_POSTS) {
      const metadata = await generateMetadata({ params: Promise.resolve({ slug: post.slug }) });
      const og = (metadata.openGraph?.images as { url: string; width: number; height: number; alt: string }[])[0]!;
      expect(og).toEqual({ url: absoluteUrl(post.cover.og.url), width: 1200, height: 630, alt: post.cover.alt });
      expect(JSON.stringify(metadata.twitter)).toContain(absoluteUrl(post.cover.og.url));
    }
  });

  it("puts the cover in the Article JSON-LD image", async () => {
    const post = BLOG_POSTS[1]!;
    render(await BlogPostPage({ params: Promise.resolve({ slug: post.slug }) }));
    const article = [...document.querySelectorAll('script[type="application/ld+json"]')]
      .flatMap((script) => {
        const data = JSON.parse(script.textContent ?? "") as Record<string, unknown>;
        return (data["@graph"] as Record<string, unknown>[] | undefined) ?? [data];
      })
      .find((node) => node["@type"] === "Article")!;
    expect(article.image).toContain(absoluteUrl(post.cover.og.url));
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
