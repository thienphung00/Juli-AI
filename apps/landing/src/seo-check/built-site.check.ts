/**
 * SEO check of the BUILT landing (P33-A, AC-33.9 relies on it). For every
 * route in the registry:
 * - exactly one <h1>, the first heading is the h1, no skipped level (h2 → h4),
 *   no empty heading, no heading inside header / nav / footer (D46.6);
 * - <title>, meta description and canonical present, equal to the registry,
 *   and unique across routes; canonical is the absolute self URL;
 * - Open Graph image + Twitter card present; no hreflang; not noindex — except
 *   a `noindex` route (blog draft awaiting owner approval), which must be;
 * - every JSON-LD block parses; Organization + WebSite on every page,
 *   BreadcrumbList on every inner page; FAQPage questions are visible on the
 *   page; no `sameAs` (D43.8); no `SoftwareApplication` and no rating or review
 *   anywhere (D48 additions 2, D43.3), `/san-pham` carries the Service.
 *
 *     pnpm build && pnpm check:seo                      # reads .next/server/app/*.html
 *     SEO_BASE_URL=http://localhost:3007 pnpm check:seo  # or fetches a running server
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { absoluteUrl, SITE_ROUTES } from "../lib/seo";

const BUILT_APP = join(__dirname, "..", "..", ".next", "server", "app");
const BASE_URL = process.env.SEO_BASE_URL?.replace(/\/$/, "");

async function loadHtml(path: string): Promise<string> {
  if (BASE_URL) {
    const response = await fetch(`${BASE_URL}${path}`, { redirect: "manual" });
    expect(response.status, `${path} status`).toBe(200);
    return response.text();
  }
  const file = join(BUILT_APP, path === "/" ? "index.html" : `${path.slice(1)}.html`);
  if (!existsSync(file)) {
    throw new Error(
      `${file} not found: run \`pnpm build\` first, or set SEO_BASE_URL (a dynamic page has no prerendered HTML).`,
    );
  }
  return readFileSync(file, "utf8");
}

interface PageFacts {
  path: string;
  title: string;
  description: string;
  canonical: string;
}

type Json = Record<string, unknown>;

function jsonLdNodes(doc: Document, path: string): Json[] {
  const nodes: Json[] = [];
  for (const script of doc.querySelectorAll('script[type="application/ld+json"]')) {
    let parsed: Json;
    try {
      parsed = JSON.parse(script.textContent ?? "") as Json;
    } catch (error) {
      throw new Error(`${path}: JSON-LD does not parse: ${String(error)}`);
    }
    expect(parsed["@context"], `${path}: JSON-LD @context`).toBe("https://schema.org");
    const graph = parsed["@graph"];
    nodes.push(...(Array.isArray(graph) ? (graph as Json[]) : [parsed]));
  }
  return nodes;
}

describe("built site SEO (every registered route)", () => {
  const facts: PageFacts[] = [];

  for (const route of SITE_ROUTES) {
    it(route.path, async () => {
      const html = await loadHtml(route.path);
      const doc = new DOMParser().parseFromString(html, "text/html");
      const where = route.path;

      // Headings.
      const headings = [...doc.querySelectorAll("h1, h2, h3, h4, h5, h6")].map((h) => ({
        level: Number(h.tagName[1]),
        text: (h.textContent ?? "").trim().slice(0, 60),
      }));
      expect(headings.filter((h) => h.level === 1), `${where}: exactly one h1`).toHaveLength(1);
      // No empty heading, and none in the header / nav / footer (the "Sản phẩm" dropdown included, D46.6).
      for (const heading of headings) expect(heading.text, `${where}: empty h${heading.level}`).not.toBe("");
      expect(
        doc.querySelectorAll(".ui-header :is(h1, h2, h3, h4, h5, h6), nav :is(h1, h2, h3, h4, h5, h6), .ui-footer :is(h1, h2, h3, h4, h5, h6)"),
        `${where}: heading inside header/nav/footer`,
      ).toHaveLength(0);
      expect(headings[0]?.level, `${where}: first heading is the h1`).toBe(1);
      headings.forEach((heading, i) => {
        if (i === 0) return;
        const previous = headings[i - 1]!;
        expect(
          heading.level,
          `${where}: "${previous.text}" (h${previous.level}) → "${heading.text}" (h${heading.level}) skips a level`,
        ).toBeLessThanOrEqual(previous.level + 1);
      });

      // Head.
      const title = doc.querySelector("title")?.textContent ?? "";
      const description = doc.querySelector('meta[name="description"]')?.getAttribute("content") ?? "";
      const canonical = doc.querySelector('link[rel="canonical"]')?.getAttribute("href") ?? "";
      expect(title, `${where}: <title>`).toBe(route.title);
      expect(description, `${where}: description`).toBe(route.description);
      expect(canonical, `${where}: canonical`).toBe(absoluteUrl(route.path));
      expect(doc.querySelector('meta[property="og:image"]'), `${where}: og:image`).not.toBeNull();
      expect(doc.querySelector('meta[property="og:locale"]')?.getAttribute("content")).toBe("vi_VN");
      expect(doc.querySelector('meta[name="twitter:card"]')?.getAttribute("content")).toBe(
        "summary_large_image",
      );
      expect(doc.querySelector('link[rel="alternate"][hreflang]'), `${where}: no hreflang`).toBeNull();
      const robots = doc.querySelector('meta[name="robots"]')?.getAttribute("content") ?? "";
      if (route.noindex) {
        // Blog draft awaiting owner approval (P33-D): rendered, never indexed.
        expect(robots, `${where}: draft is noindex`).toMatch(/noindex/);
      } else {
        expect(robots, `${where}: indexable`).not.toMatch(/noindex/);
        // …and an indexable page never links to one (the /blog index lists published posts only).
        const hrefs = [...doc.querySelectorAll("a[href]")].map((a) => a.getAttribute("href") ?? "");
        for (const hidden of SITE_ROUTES.filter((r) => r.noindex)) {
          expect(hrefs, `${where}: links the noindex page ${hidden.path}`).not.toContain(hidden.path);
        }
      }
      facts.push({ path: route.path, title, description, canonical });

      // JSON-LD.
      const nodes = jsonLdNodes(doc, where);
      const types = nodes.map((node) => node["@type"]);
      expect(types, `${where}: Organization`).toContain("Organization");
      expect(types, `${where}: WebSite`).toContain("WebSite");
      if (route.path !== "/") expect(types, `${where}: BreadcrumbList`).toContain("BreadcrumbList");
      expect(JSON.stringify(nodes), `${where}: no sameAs (D43.8)`).not.toContain("sameAs");
      expect(types, `${where}: no SoftwareApplication (D48 additions 2)`).not.toContain("SoftwareApplication");
      expect(JSON.stringify(nodes), `${where}: no rating or review (D43.3)`).not.toMatch(
        /aggregateRating|"review"/,
      );
      if (route.path === "/san-pham") expect(types, `${where}: Service`).toContain("Service");
      const visibleText = (doc.querySelector("main")?.textContent ?? "").replace(/\s+/g, " ");
      for (const faq of nodes.filter((node) => node["@type"] === "FAQPage")) {
        for (const question of faq.mainEntity as Json[]) {
          expect(visibleText, `${where}: FAQ question rendered`).toContain(String(question.name));
        }
      }
    });
  }

  it("titles, descriptions and canonicals are unique", () => {
    expect(facts).toHaveLength(SITE_ROUTES.length);
    for (const key of ["title", "description", "canonical"] as const) {
      const values = facts.map((fact) => fact[key]);
      expect(new Set(values).size, `duplicate ${key}`).toBe(values.length);
    }
  });
});
