import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import BlogPostPage, { generateMetadata, generateStaticParams } from "../app/blog/[slug]/page";
import BlogIndexPage from "../app/blog/page";
import sitemap from "../app/sitemap";
import { countWords, markdownLinks, parseMarkdown, slugify, tableOfContents } from "../components/blog/markdown";
import {
  BLOG_CATEGORIES,
  BLOG_FIGURES,
  BLOG_POSTS,
  blogCover,
  COMPETITORS,
  competitorNamesIn,
  getPost,
  isCompetitorUrl,
  relatedPosts,
  showDraftsOnIndex,
} from "../content/blog";
import type { BlogPostFormat, BlogPostMeta } from "../content/blog/types";
import { absoluteUrl, getRoute, metadataForRoute, SITE_ROUTES, sitemapEntries } from "../lib/seo";
import { blogPostPath, buildBlogRoutes } from "../lib/seo/routes/blog";

/** P33-C product pages every pillar post links to (all registered since integration). */
const PRODUCT_PAGES = new Set([
  "/san-pham/phan-tich-shop",
  "/san-pham/de-xuat-va-thuc-thi",
  "/san-pham/do-luong-gmv",
  "/ket-noi/tiktok-shop",
]);

/** The tools hub (D49.2) and the listicles that link it instead of Juli's product pages. */
const TOOLS_HUB = "cong-cu-cho-nha-ban-tiktok-shop-2026";
const NO_JULI_IN_BODY = new Set([
  "phan-mem-quan-ly-ban-hang-da-kenh-2026",
  "cong-cu-ai-tao-anh-video-san-pham-tiktok-shop",
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
  format: "pain",
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

  it("every post is registered; drafts are noindex and out of the real sitemap, published posts are in it", () => {
    const urls = sitemap().map((entry) => entry.url);
    expect(urls).toContain(absoluteUrl("/blog"));
    for (const post of BLOG_POSTS) {
      const route = getRoute(blogPostPath(post.slug));
      expect(Boolean(route.noindex), post.slug).toBe(post.status !== "published");
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
    const post = BLOG_POSTS.find((p) => p.status === "draft")!;
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

  it("sets article metadata with published/modified times; noindex only for a draft", async () => {
    for (const post of BLOG_POSTS) {
      const metadata = await generateMetadata({ params: Promise.resolve({ slug: post.slug }) });
      if (post.status === "draft") expect(metadata.robots, post.slug).toEqual({ index: false, follow: true });
      else expect(metadata.robots, post.slug).not.toEqual({ index: false, follow: true });
    }
    const post = BLOG_POSTS.find((p) => p.status === "draft")!;
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

/**
 * D56 G5: word range by post type. The targets are pain 1,500–2,500 and news
 * 800–1,500; `max` is the tolerance above the target (pain 3,000, news 2,000)
 * and applies only to posts written after D56: the two pre-D56 pain posts
 * were written to the old 3,000+ floor and keep their length. Pillar and
 * comparison posts have no upper bound. `minH2`: table-of-contents entries.
 */
const WORDS: Record<BlogPostFormat, { min: number; max?: number; minH2: number }> = {
  pillar: { min: 3000, minH2: 5 },
  comparison: { min: 3000, minH2: 5 },
  pain: { min: 1500, max: 3000, minH2: 5 },
  news: { min: 800, max: 2000, minH2: 3 },
};

/**
 * Posts written before D56 (2026-10-17). The FAQ 3–5 rule and the word cap
 * apply to every pain / news post written after them; these keep what they have.
 */
const PRE_D56_POSTS = new Set([
  "chi-so-tiktok-shop-ctr-ctor-aov",
  "toi-uu-the-san-pham-tiktok-shop",
  "cong-cu-cho-nha-ban-tiktok-shop-2026",
  "gmv-la-gi-tiktok-shop",
  "tiktok-shop-khong-ra-don",
  "doanh-thu-tiktok-shop-giam",
  "phan-mem-quan-ly-ban-hang-da-kenh-2026",
  "cong-cu-phan-tich-tiktok-shop-2026",
  "cong-cu-ai-tao-anh-video-san-pham-tiktok-shop",
]);

describe("post content (D43.7, D56 G5)", () => {
  for (const meta of BLOG_POSTS) {
    const post = getPost(meta.slug)!;

    it(`${meta.slug}: length fits its format (${meta.format}), H2 → H3 only, unique headings`, () => {
      const rule = WORDS[meta.format];
      expect(rule, `unknown format ${meta.format}`).toBeDefined();
      const words = countWords(post.body);
      expect(words, `${meta.slug}: ${meta.format} needs ${rule.min}+ words`).toBeGreaterThanOrEqual(rule.min);
      if (rule.max && !PRE_D56_POSTS.has(meta.slug)) {
        expect(words, `${meta.slug}: over ${rule.max} words, trim it or make it a pillar`).toBeLessThanOrEqual(rule.max);
      }
      const blocks = parseMarkdown(post.body);
      expect(blocks[0]?.kind).not.toBe("h3");
      const ids = blocks.flatMap((block) => ("id" in block ? [block.id] : []));
      expect(new Set(ids).size).toBe(ids.length);
      expect(tableOfContents(blocks).length).toBeGreaterThanOrEqual(rule.minH2);
    });

    it(`${meta.slug}: FAQ 3–5 questions for a new pain / news post (D56 G5)`, () => {
      const faq = meta.faq?.length ?? 0;
      if (PRE_D56_POSTS.has(meta.slug) || (meta.format !== "pain" && meta.format !== "news")) return;
      expect(faq).toBeGreaterThanOrEqual(3);
      expect(faq).toBeLessThanOrEqual(5);
    });

    it(`${meta.slug}: no link to a competitor / vendor domain, in the body or the sources (D56 G2)`, () => {
      const external = markdownLinks(post.body).filter((href) => /^https?:\/\//.test(href));
      expect(external.filter(isCompetitorUrl), "body").toEqual([]);
      const linked = meta.sources.flatMap((source) => (source.url ? [source.url] : []));
      expect(linked.filter(isCompetitorUrl), "sources").toEqual([]);
      for (const source of meta.sources) {
        if (source.url === undefined) expect(source.checkedAt, source.title).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      }
    });

    it(`${meta.slug}: names competitors only where G1 allows`, () => {
      const text = [
        post.body,
        meta.title,
        meta.seoTitle,
        meta.description,
        meta.excerpt,
        ...(meta.faq ?? []).flatMap((item) => [item.question, item.answer]),
        ...meta.sources.map((source) => source.title),
      ].join("\n");
      // Adjacent ring (AI chatbots / sales agents): never named, in any post.
      expect(competitorNamesIn(text, "adjacent")).toEqual([]);
      // Direct ring: only in comparison posts (category "tools").
      if (meta.category !== "tools") expect(competitorNamesIn(text, "direct")).toEqual([]);
    });

    it(`${meta.slug}: internal links resolve, and it links the product pages`, () => {
      const internal = markdownLinks(post.body).filter((href) => href.startsWith("/"));
      const registered = new Set(SITE_ROUTES.map((route) => route.path));
      for (const href of internal) {
        expect(registered.has(href), href).toBe(true);
      }
      if (NO_JULI_IN_BODY.has(meta.slug)) {
        // D49.2 a / c: listicles that must not mention Juli link the tools hub, not the product pages.
        expect(internal).toContain(`/blog/${TOOLS_HUB}`);
        expect(internal.filter((href) => href.startsWith("/san-pham") || href.startsWith("/ket-noi"))).toEqual([]);
        expect(post.body).not.toMatch(/Juli/);
        return;
      }
      if (meta.format === "news") {
        // D56 G3: a TMĐT-change post (tax, fees, policy) links /san-pham plus one
        // relevant page; forcing all product pages into it would read as an ad.
        expect(internal, "/san-pham").toContain("/san-pham");
        expect(internal.filter((href) => href !== "/san-pham" && href !== "/dang-ky").length).toBeGreaterThanOrEqual(1);
        return;
      }
      for (const page of ["/san-pham", ...PRODUCT_PAGES]) {
        expect(internal, page).toContain(page);
      }
    });

    it(`${meta.slug}: no em dash in visible copy (D46.4)`, () => {
      for (const text of [post.body, meta.title, meta.seoTitle, meta.description, meta.excerpt, meta.cover.alt]) {
        expect(text).not.toContain("—");
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

/** Intrinsic size of a WebP file (VP8X, lossy VP8 or lossless VP8L header). */
function webpSize(file: string): { width: number; height: number } {
  const buf = readFileSync(file);
  expect(buf.toString("ascii", 0, 4) + buf.toString("ascii", 8, 12), file).toBe("RIFFWEBP");
  const chunk = buf.toString("ascii", 12, 16);
  if (chunk === "VP8X") {
    return { width: 1 + buf.readUIntLE(24, 3), height: 1 + buf.readUIntLE(27, 3) };
  }
  if (chunk === "VP8 ") {
    return { width: buf.readUInt16LE(26) & 0x3fff, height: buf.readUInt16LE(28) & 0x3fff };
  }
  const bits = buf.readUInt32LE(21);
  return { width: (bits & 0x3fff) + 1, height: ((bits >> 14) & 0x3fff) + 1 };
}

const VIETNAMESE = /[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]/i;
const FIGURE_POSTS = [
  "gmv-la-gi-tiktok-shop",
  "tiktok-shop-khong-ra-don",
  "doanh-thu-tiktok-shop-giam",
  "san-pham-tiktok-shop-khong-co-luot-hien-thi",
  "video-tiktok-nhieu-view-khong-ra-don",
  "live-tiktok-shop-khong-ra-don",
  "khach-xem-nhung-khong-mua-tiktok-shop",
  "tang-gia-tri-don-hang-trung-binh-tiktok-shop",
];

function figureIds(body: string): string[] {
  return parseMarkdown(body).flatMap((block) => (block.kind === "figure" ? [block.id] : []));
}

describe("inline figures (D48 additions 7, P39-C)", () => {
  it("each P39-B post has 3–8 figures, every post 0–8, and every figure is defined and used once per post", () => {
    const used = new Set<string>();
    for (const post of BLOG_POSTS) {
      const ids = figureIds(getPost(post.slug)!.body);
      expect(ids.length, post.slug).toBeGreaterThanOrEqual(FIGURE_POSTS.includes(post.slug) ? 3 : 0);
      expect(ids.length, post.slug).toBeLessThanOrEqual(8);
      expect(new Set(ids).size, `${post.slug}: a figure twice`).toBe(ids.length);
      for (const id of ids) {
        expect(BLOG_FIGURES[id], `${post.slug}: {{hinh:${id}}}`).toBeDefined();
        used.add(id);
      }
    }
    expect([...used].sort()).toEqual(Object.keys(BLOG_FIGURES).sort());
  });

  for (const [id, figure] of Object.entries(BLOG_FIGURES)) {
    it(`${id}: files exist with their width/height, Vietnamese alt and caption`, () => {
      for (const variant of [...figure.variants, ...figure.mobileVariants]) {
        expect(variant.avif, `${id}: avif`).toBeDefined();
        for (const file of [variant.avif!, variant.webp]) {
          expect(existsSync(join(PUBLIC_DIR, file)), file).toBe(true);
        }
        expect(webpSize(join(PUBLIC_DIR, variant.webp)), variant.webp).toEqual({
          width: variant.width,
          height: variant.height,
        });
      }
      expect(figure.variants.length).toBeGreaterThan(0);
      expect(figure.mobileVariants.length, `${id}: a phone variant`).toBeGreaterThan(0);
      for (const text of [figure.alt, figure.caption]) {
        expect(text.trim().length).toBeGreaterThan(20);
        expect(text).toMatch(VIETNAMESE);
        expect(text, `${id}: no em dash (D46.4)`).not.toContain("—");
      }
      if (figure.kind === "screenshot") {
        expect(figure.caption.startsWith("Dữ liệu mẫu · "), id).toBe(true);
        expect(figure.alt).toMatch(/\(dữ liệu mẫu\)$/);
        expect(figure.variants[0]!.webp).toMatch(/^\/media\/cap-/);
      } else {
        expect(figure.variants[0]!.webp).toMatch(/^\/media\/blog-fig-[a-z0-9-]+-v\d+-720\.webp$/);
        // A diagram with figures in it says they are hypothetical (the image carries the same pill).
        if (/\d[\d.]{2,}|\d %/.test(figure.alt)) expect(figure.alt.toLowerCase(), id).toContain("ví dụ giả định");
      }
    });
  }

  const postsWithFigures = BLOG_POSTS.map((p) => p.slug).filter((slug) => figureIds(getPost(slug)!.body).length > 0);
  for (const slug of postsWithFigures) {
    it(`${slug}: renders every figure lazy, sized, captioned; only the cover is eager`, async () => {
      render(await BlogPostPage({ params: Promise.resolve({ slug }) }));
      const post = getPost(slug)!;
      const ids = figureIds(post.body);
      const figures = [...document.querySelectorAll(".lp-prose figure")];
      expect(figures).toHaveLength(ids.length);
      figures.forEach((element, index) => {
        const figure = BLOG_FIGURES[ids[index]!]!;
        const img = element.querySelector("img")!;
        const largest = [...figure.variants].sort((a, b) => b.width - a.width)[0]!;
        expect(img).toHaveAttribute("alt", figure.alt);
        expect(img).toHaveAttribute("loading", "lazy");
        expect(img.getAttribute("fetchpriority") ?? "auto").not.toBe("high");
        expect(img).toHaveAttribute("width", String(largest.width));
        expect(img).toHaveAttribute("height", String(largest.height));
        expect(element.querySelector("figcaption")).toHaveTextContent(figure.caption);
        const mobile = element.querySelector('source[media="(max-width: 640px)"]');
        expect(mobile, `${ids[index]}: phone source`).not.toBeNull();
        expect(mobile).toHaveAttribute("width");
        expect(mobile).toHaveAttribute("height");
      });
      // In the post (the header / footer logo mark is outside it): only the cover is eager.
      const eager = [...document.querySelectorAll(".lp-post img")].filter((img) => img.getAttribute("loading") !== "lazy");
      expect(eager.map((img) => img.getAttribute("alt"))).toEqual([post.cover.alt]);
    });
  }

  it("keeps the Article JSON-LD image to the cover (existing pattern)", async () => {
    render(await BlogPostPage({ params: Promise.resolve({ slug: FIGURE_POSTS[0]! }) }));
    const json = [...document.querySelectorAll('script[type="application/ld+json"]')]
      .map((script) => script.textContent ?? "")
      .join(" ");
    expect(json).not.toContain("blog-fig-");
    expect(json).not.toContain("/media/cap-");
  });
});

describe("competitor registry (D56 G1 / G2)", () => {
  it("has the three rings, each name and domain once per ring", () => {
    for (const ring of ["direct", "adjacent", "not-competing"] as const) {
      const entries = COMPETITORS.filter((c) => c.ring === ring);
      expect(entries.length, ring).toBeGreaterThan(0);
      const names = entries.flatMap((c) => c.names);
      expect(new Set(names).size, ring).toBe(names.length);
    }
    for (const name of ["Sapo", "FastMoss", "Kalodata", "Metric", "Atosa"]) {
      expect(COMPETITORS.find((c) => c.names.includes(name))?.ring, name).toBe("direct");
    }
    for (const name of ["Preny", "Fchat", "Botcake", "AhaChat", "Smax", "Hana", "Harasocial"]) {
      expect(COMPETITORS.find((c) => c.names.includes(name))?.ring, name).toBe("adjacent");
    }
    for (const name of ["CapCut", "Canva", "Photoroom", "Higgsfield", "Pippit", "KiotViet", "BigSeller", "Haravan", "MISA eShop"]) {
      expect(COMPETITORS.find((c) => c.names.includes(name))?.ring, name).toBe("not-competing");
    }
  });

  it("matches registry hosts and subdomains, and leaves primary sources linked", () => {
    expect(isCompetitorUrl("https://www.sapo.vn/bang-gia.html")).toBe(true);
    expect(isCompetitorUrl("https://pos.pancake.vn/")).toBe(true);
    expect(isCompetitorUrl("https://hotro.metric.vn/")).toBe(true);
    expect(isCompetitorUrl("https://notsapo.vn/")).toBe(false);
    for (const primary of [
      "https://seller-vn.tiktok.com/university/essay?knowledge_id=10008597",
      "https://ads.tiktok.com/help/article/about-symphony-creative-studio?lang=vi",
      "https://banhang.shopee.vn/edu/home",
      "https://thuvienphapluat.vn/van-ban/Thuong-mai/Nghi-dinh-52-2013-ND-CP-thuong-mai-dien-tu-198578.aspx",
      "https://www.gdt.gov.vn/",
      "/san-pham",
    ]) {
      expect(isCompetitorUrl(primary), primary).toBe(false);
    }
  });

  it("finds names as whole words only", () => {
    expect(competitorNamesIn("So với Sapo và FastMoss", "direct")).toEqual(["Sapo", "FastMoss"]);
    expect(competitorNamesIn("metrics, Metrics, Sapodilla", "direct")).toEqual([]);
    expect(competitorNamesIn("chatbot trả lời tin nhắn", "adjacent")).toEqual([]);
  });

  it("renders a competitor source as plain text with its check date, a primary source as a link", async () => {
    const slug = "cong-cu-cho-nha-ban-tiktok-shop-2026";
    render(await BlogPostPage({ params: Promise.resolve({ slug }) }));
    const sources = screen.getByRole("heading", { level: 2, name: "Nguồn tham khảo" }).closest("section")!;
    const sapo = within(sources).getByText("Sapo").closest("li")!;
    expect(sapo.querySelector("a")).toBeNull();
    expect(sapo).toHaveTextContent("Sapo (kiểm tra 15/10/2026)");
    const academy = within(sources).getByRole("link", { name: /Học viện TikTok Shop: Lưu lượng truy cập sản phẩm/ });
    expect(academy.getAttribute("href")).toMatch(/^https:\/\/seller-vn\.tiktok\.com\//);
    for (const link of within(sources).getAllByRole("link")) {
      expect(isCompetitorUrl(link.getAttribute("href") ?? ""), link.getAttribute("href")!).toBe(false);
    }
  });
});

describe("markdown subset", () => {
  it("parses a {{hinh:<id>}} line as a figure, not a word, and rejects a malformed one", () => {
    const blocks = parseMarkdown("đoạn một\n{{hinh:gmv-pheu}}\nđoạn hai");
    expect(blocks).toEqual([
      { kind: "p", text: "đoạn một" },
      { kind: "figure", id: "gmv-pheu" },
      { kind: "p", text: "đoạn hai" },
    ]);
    expect(countWords("một hai\n\n{{hinh:gmv-pheu}}\n\nba")).toBe(3);
    expect(() => parseMarkdown("{{hinh: Sai}}")).toThrow();
  });

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
