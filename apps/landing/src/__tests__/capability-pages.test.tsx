import { render } from "@testing-library/react";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import KetNoiPage from "../app/ket-noi/tiktok-shop/page";
import DeXuatPage from "../app/san-pham/de-xuat-va-thuc-thi/page";
import DoLuongPage from "../app/san-pham/do-luong-gmv/page";
import PhanTichPage from "../app/san-pham/phan-tich-shop/page";
import { DEMO_URL, LOGIN_URL } from "../lib/site";

/**
 * AC-33.7 (P33-C, D43.4): the three capability pages and /ket-noi/tiktok-shop —
 * one H1, one labelled sample screenshot (AVIF/WebP, sized) per content H2,
 * an FAQ that is exactly the FAQPage JSON-LD, internal links and both CTAs.
 */
const PAGES = [
  { name: "/san-pham/phan-tich-shop", Page: PhanTichPage, software: true },
  { name: "/san-pham/de-xuat-va-thuc-thi", Page: DeXuatPage, software: true },
  { name: "/san-pham/do-luong-gmv", Page: DoLuongPage, software: true },
  { name: "/ket-noi/tiktok-shop", Page: KetNoiPage, software: false },
] as const;

const PUBLIC_DIR = join(__dirname, "..", "..", "public");

function jsonLd(container: HTMLElement): Array<Record<string, unknown>> {
  const node = container.querySelector('script[type="application/ld+json"]');
  const parsed = JSON.parse(node?.textContent ?? "{}") as Record<string, unknown>;
  return ((parsed["@graph"] as Array<Record<string, unknown>> | undefined) ?? [parsed]);
}

describe.each(PAGES)("$name (AC-33.7)", ({ Page, software }) => {
  it("has one H1 and a labelled, sized sample screenshot under every content H2", () => {
    const { container, unmount } = render(<Page />);
    expect(container.querySelectorAll("h1")).toHaveLength(1);
    const sections = [...container.querySelectorAll("main section")].filter(
      (section) => section.querySelector(":scope > h2") && section.id !== "cau-hoi",
    );
    expect(sections.length).toBeGreaterThanOrEqual(4);
    for (const section of sections) {
      const images = section.querySelectorAll("figure img");
      expect(images, section.id).toHaveLength(1);
      const img = images[0]!;
      expect(img.getAttribute("alt")).toMatch(/\(dữ liệu mẫu\)$/);
      expect(Number(img.getAttribute("width"))).toBeGreaterThan(0);
      expect(Number(img.getAttribute("height"))).toBeGreaterThan(0);
      expect(section.querySelector("figcaption")).toHaveTextContent(/^Dữ liệu mẫu/);
      const sources = [...section.querySelectorAll("picture source")].map((s) => s.getAttribute("type"));
      expect(sources).toContain("image/webp");
      for (const src of [img.getAttribute("src"), ...[...section.querySelectorAll("source")].flatMap((s) =>
        (s.getAttribute("srcset") ?? "").split(",").map((part) => part.trim().split(" ")[0]),
      )]) {
        expect(existsSync(join(PUBLIC_DIR, src ?? "missing")), String(src)).toBe(true);
      }
    }
    unmount();
  });

  it("renders exactly the FAQ in FAQPage, plus breadcrumbs and the right schema", () => {
    const { container, unmount } = render(<Page />);
    const graph = jsonLd(container);
    const types = graph.map((entity) => entity["@type"]);
    expect(types).toContain("BreadcrumbList");
    expect(types.includes("SoftwareApplication")).toBe(software);
    const faq = graph.find((entity) => entity["@type"] === "FAQPage");
    const questions = (faq?.mainEntity as Array<{ name: string }>).map((q) => q.name);
    const shown = [...container.querySelectorAll("#cau-hoi dt")].map((dt) => dt.textContent);
    expect(shown).toEqual(questions);
    unmount();
  });

  it("links the other capability pages, /privacy or /san-pham, the blog and both CTAs", () => {
    const { container, unmount } = render(<Page />);
    const hrefs = new Set([...container.querySelectorAll("main a")].map((a) => a.getAttribute("href")));
    expect(hrefs.has("/blog")).toBe(true);
    expect(hrefs.has("/privacy") || hrefs.has("/san-pham")).toBe(true);
    const capabilityLinks = PAGES.map((p) => p.name).filter((href) => hrefs.has(href));
    expect(capabilityLinks.length).toBeGreaterThanOrEqual(2);
    const ctas = [...container.querySelectorAll("main a")];
    expect(ctas.some((a) => a.textContent === "Dùng thử 3 tháng" && a.getAttribute("href") === LOGIN_URL)).toBe(true);
    expect(ctas.some((a) => a.textContent === "Xem demo" && a.getAttribute("href") === DEMO_URL)).toBe(true);
    unmount();
  });

  it("states no testimonial and names Shopee only as in progress", () => {
    const { container, unmount } = render(<Page />);
    const text = container.querySelector("main")?.textContent ?? "";
    expect(text).not.toMatch(/khách hàng nói|đánh giá của khách|case study/i);
    for (const match of text.matchAll(/Shopee/g)) {
      const around = text.slice(Math.max(0, (match.index ?? 0) - 40), (match.index ?? 0) + 80);
      expect(around).toMatch(/tích hợp|Juli hỗ trợ Shopee/);
    }
    unmount();
  });
});
