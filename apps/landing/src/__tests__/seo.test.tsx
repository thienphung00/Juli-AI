import { readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { describe, expect, it } from "vitest";

import { RENAMED_PATHS } from "../../next.config";
import sitemap from "../app/sitemap";
import {
  absoluteUrl,
  articleSchema,
  breadcrumbSchema,
  breadcrumbTrail,
  buildMetadata,
  DESCRIPTION_MAX_LENGTH,
  faqPageSchema,
  getRoute,
  hasRoute,
  organizationSchema,
  serializeJsonLd,
  SITE_ROUTES,
  softwareApplicationSchema,
  TITLE_MAX_LENGTH,
  TITLE_SUFFIX,
  videoObjectSchema,
  websiteSchema,
} from "../lib/seo";
import { HERO_VIDEO_SCHEMA } from "../lib/media";
import { COMPANY } from "../lib/site";

const APP_DIR = join(__dirname, "..", "app");

/** Site paths of every `page.tsx` under src/app (route groups stripped). */
function pagePaths(dir = APP_DIR): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return entry === "api" ? [] : pagePaths(path);
    if (entry !== "page.tsx") return [];
    const segments = relative(APP_DIR, dir)
      .split(sep)
      .filter((segment) => segment && !segment.startsWith("("));
    return [`/${segments.join("/")}`];
  });
}

function matchesPage(routePath: string, page: string): boolean {
  const a = routePath.split("/");
  const b = page.split("/");
  return a.length === b.length && b.every((segment, i) => segment.startsWith("[") || segment === a[i]);
}

describe("route registry (AC-33.1)", () => {
  it("registers every page, and every registered route has a page", () => {
    const pages = pagePaths();
    for (const page of pages.filter((p) => !p.includes("["))) {
      expect(hasRoute(page), `${page} has a page.tsx but is not in src/lib/seo/routes/`).toBe(true);
    }
    for (const route of SITE_ROUTES) {
      expect(
        pages.some((page) => matchesPage(route.path, page)),
        `${route.path} is registered but has no page.tsx`,
      ).toBe(true);
    }
  });

  it("gives every route a unique, well-sized title and description", () => {
    const titles = new Set<string>();
    const descriptions = new Set<string>();
    const paths = new Set<string>();
    for (const route of SITE_ROUTES) {
      expect(route.path, route.path).toMatch(/^\/(?:[a-z0-9-]+(?:\/[a-z0-9-]+)*)?$/);
      expect(route.title.endsWith(TITLE_SUFFIX), route.title).toBe(true);
      expect(route.title.length, route.title).toBeLessThanOrEqual(TITLE_MAX_LENGTH);
      expect(route.description.length, route.description).toBeLessThanOrEqual(DESCRIPTION_MAX_LENGTH);
      expect(route.description.length, route.description).toBeGreaterThanOrEqual(70);
      expect(route.lastModified, route.path).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(Number.isNaN(Date.parse(route.lastModified))).toBe(false);
      for (const [set, value] of [
        [titles, route.title],
        [descriptions, route.description],
        [paths, route.path],
      ] as const) {
        expect(set.has(value), `duplicate: ${value}`).toBe(false);
        set.add(value);
      }
      // Every parent exists, so the breadcrumb trail resolves.
      expect(breadcrumbTrail(route.path)[0]).toEqual({ name: "Trang chủ", path: "/" });
    }
  });

  it("feeds the sitemap with absolute URLs and lastmod", () => {
    const entries = sitemap();
    // Every indexable route; `noindex` ones (blog drafts, P33-D) are left out.
    expect(entries.map((entry) => entry.url)).toEqual(
      SITE_ROUTES.filter((r) => !r.noindex).map((r) => absoluteUrl(r.path)),
    );
    for (const entry of entries) expect(entry.lastModified).toBeTruthy();
  });

  it("301s each renamed URL to a registered page, never to an unknown one", () => {
    for (const { source, destination } of RENAMED_PATHS) {
      expect(hasRoute(destination), destination).toBe(true);
      expect(hasRoute(source), source).toBe(false);
    }
    expect(RENAMED_PATHS).toContainEqual({ source: "/product", destination: "/san-pham" });
  });
});

describe("buildMetadata (AC-33.1)", () => {
  it("returns title, description, absolute canonical, OG and Twitter", () => {
    const route = getRoute("/san-pham");
    const metadata = buildMetadata("/san-pham");
    expect(metadata.title).toEqual({ absolute: route.title });
    expect(metadata.description).toBe(route.description);
    expect(metadata.alternates).toEqual({ canonical: "https://app-juli.com/san-pham" });
    expect(metadata.alternates).not.toHaveProperty("languages");
    expect(metadata.openGraph).toMatchObject({
      title: route.title,
      url: "https://app-juli.com/san-pham",
      type: "website",
      locale: "vi_VN",
      siteName: "Juli AI",
      images: [{ url: "https://app-juli.com/og/juli-ai-default-v2.png", width: 1200, height: 630 }],
    });
    expect(metadata.twitter).toMatchObject({ card: "summary_large_image", title: route.title });
  });

  it("uses the bare origin as the home canonical (what Next prints)", () => {
    expect(buildMetadata("/").alternates).toEqual({ canonical: "https://app-juli.com" });
  });

  it("refuses an unregistered path", () => {
    expect(() => buildMetadata("/khong-co")).toThrow(/not in the route registry/);
  });
});

describe("JSON-LD builders (AC-33.1)", () => {
  it("describes the operating company with tax ID, address and contact e-mail, no sameAs", () => {
    const org = organizationSchema();
    expect(org).toMatchObject({
      "@type": "Organization",
      legalName: "Công ty TNHH Công Nghệ Juli AI",
      taxID: "0319617654",
      address: {
        "@type": "PostalAddress",
        streetAddress: "1B Đường số 30 Trần Não",
        addressLocality: "Phường An Khánh",
        addressRegion: "Thành phố Hồ Chí Minh",
        addressCountry: "VN",
      },
      contactPoint: { "@type": "ContactPoint", email: COMPANY.email },
    });
    expect(JSON.stringify(org)).not.toMatch(/sameAs|telephone/);
    expect(websiteSchema()).toMatchObject({ "@type": "WebSite", url: "https://app-juli.com" });
  });

  it("builds breadcrumbs from the registry", () => {
    expect(breadcrumbSchema("/about")).toEqual({
      "@type": "BreadcrumbList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: "Trang chủ", item: "https://app-juli.com" },
        { "@type": "ListItem", position: 2, name: "Giới thiệu", item: "https://app-juli.com/about" },
      ],
    });
  });

  it("prices the software at 500000 VND as a BusinessApplication", () => {
    expect(softwareApplicationSchema({ path: "/san-pham" })).toMatchObject({
      "@type": "SoftwareApplication",
      applicationCategory: "BusinessApplication",
      offers: { "@type": "Offer", price: 500000, priceCurrency: "VND" },
    });
  });

  it("builds FAQPage, Article and VideoObject", () => {
    expect(() => faqPageSchema([])).toThrow();
    expect(faqPageSchema([{ question: "Q?", answer: "A." }])).toMatchObject({
      "@type": "FAQPage",
      mainEntity: [{ "@type": "Question", name: "Q?", acceptedAnswer: { text: "A." } }],
    });
    expect(articleSchema({ path: "/about", datePublished: "2026-10-15" })).toMatchObject({
      "@type": "Article",
      dateModified: "2026-10-15",
      mainEntityOfPage: { "@id": "https://app-juli.com/about" },
    });
    expect(videoObjectSchema(HERO_VIDEO_SCHEMA)).toMatchObject({
      "@type": "VideoObject",
      contentUrl: "https://app-juli.com/videos/juli-demo.mp4",
      thumbnailUrl: ["https://app-juli.com/media/home-demo-poster-v1-1280.webp"],
      duration: "PT1M4S",
    });
  });

  it("serialises with @context and cannot close its <script>", () => {
    const json = serializeJsonLd({ "@type": "Thing", name: "</script><b>" });
    expect(json).not.toContain("</script>");
    expect(JSON.parse(json)).toEqual({
      "@context": "https://schema.org",
      "@type": "Thing",
      name: "</script><b>",
    });
    expect(JSON.parse(serializeJsonLd([websiteSchema()]))).toHaveProperty("@graph");
  });
});
