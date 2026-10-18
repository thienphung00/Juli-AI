import { render } from "@testing-library/react";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import KetNoiPage from "../app/ket-noi/tiktok-shop/page";
import LandingPage from "../app/page";
import SanPhamPage from "../app/san-pham/page";
import DeXuatPage from "../app/san-pham/de-xuat-va-thuc-thi/page";
import DoLuongPage from "../app/san-pham/do-luong-gmv/page";
import PhanTichPage from "../app/san-pham/phan-tich-shop/page";
import { DEMO_URL, SIGNUP_URL, TRIAL_CTA_LABEL } from "../lib/site";

/**
 * AC-33.7 (P33-C, D43.4) + AC-34.3 (P34-C, D44): the three capability pages and
 * /ket-noi/tiktok-shop — one H1, one labelled sample screenshot (AVIF/WebP,
 * sized, captioned "Dữ liệu mẫu") per content H2, an FAQ that is exactly the
 * FAQPage JSON-LD, internal links and both CTAs. Since P34-C the trial CTA is
 * "Dùng thử miễn phí 3 tháng" → SIGNUP_URL (D43 additions 2), the FAQ is the
 * `FaqList` accordion and each page carries its block-built diagram.
 */
const PAGES = [
  { name: "/san-pham/phan-tich-shop", Page: PhanTichPage, service: true },
  { name: "/san-pham/de-xuat-va-thuc-thi", Page: DeXuatPage, service: true },
  { name: "/san-pham/do-luong-gmv", Page: DoLuongPage, service: true },
  { name: "/ket-noi/tiktok-shop", Page: KetNoiPage, service: false },
] as const;

const PUBLIC_DIR = join(__dirname, "..", "..", "public");

function jsonLd(container: HTMLElement): Array<Record<string, unknown>> {
  const node = container.querySelector('script[type="application/ld+json"]');
  const parsed = JSON.parse(node?.textContent ?? "{}") as Record<string, unknown>;
  return ((parsed["@graph"] as Array<Record<string, unknown>> | undefined) ?? [parsed]);
}

describe.each(PAGES)("$name (AC-33.7)", ({ Page, service }) => {
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
      // The screenshot's own caption (a section may also hold a diagram figure).
      expect(img.closest("figure.ui-shot")?.querySelector(":scope > figcaption")).toHaveTextContent(
        /^Dữ liệu mẫu/,
      );
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
    expect(types).not.toContain("SoftwareApplication");
    const page = graph.find((entity) => entity["@type"] === "WebPage");
    expect(Boolean(page)).toBe(service);
    if (page) expect(page.about).toEqual({ "@id": "https://app-juli.com/#service" });
    const faq = graph.find((entity) => entity["@type"] === "FAQPage");
    const questions = (faq?.mainEntity as Array<{ name: string }>).map((q) => q.name);
    const shown = [...container.querySelectorAll("#cau-hoi summary")].map((q) => q.textContent);
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
    for (const testId of ["cap-trial-cta", "cap-final-trial-cta"]) {
      const cta = container.querySelector(`[data-testid="${testId}"]`);
      expect(cta, testId).toHaveAttribute("href", SIGNUP_URL);
      expect(cta, testId).toHaveTextContent(TRIAL_CTA_LABEL);
    }
    for (const testId of ["cap-demo-cta", "cap-final-demo-cta"]) {
      const cta = container.querySelector(`[data-testid="${testId}"]`);
      expect(cta, testId).toHaveAttribute("href", DEMO_URL);
      expect(cta, testId).toHaveTextContent("Xem demo");
    }
    unmount();
  });

  it("follows Product.dc.html: breadcrumb, framed hero shot, side TOC to every section, mobile crops", () => {
    const { container, unmount } = render(<Page />);
    expect(container.querySelector('nav[aria-label="Breadcrumb"] [aria-current="page"]')).not.toBeNull();
    const hero = container.querySelector('section[aria-labelledby="cap-heading"]');
    expect(hero?.querySelector(".ui-shot__chrome")).not.toBeNull();
    expect(hero?.querySelector("figcaption")).toHaveTextContent(/^Dữ liệu mẫu/);
    const tocTargets = [...container.querySelectorAll(".ui-toc__desktop a")].map((a) =>
      a.getAttribute("href")?.slice(1),
    );
    expect(tocTargets.length).toBeGreaterThanOrEqual(5);
    for (const id of tocTargets) expect(container.querySelector(`[id="${id}"]`), id).not.toBeNull();
    // At least the shots with a mobile crop in screens.ts serve it at ≤ 640 px.
    expect(container.querySelectorAll('main section[id] picture source[media]').length).toBeGreaterThanOrEqual(3);
    // One dark CTA band.
    expect(container.querySelectorAll(".ui-section--dark")).toHaveLength(1);
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

describe("capability-page diagrams (AC-34.3, built in markup)", () => {
  it("Phân tích: the funnel with CTOR marked and the five streams", () => {
    const { container, unmount } = render(<PhanTichPage />);
    const funnel = container.querySelector("#pheu .ui-funnel [role=img]");
    expect(funnel?.getAttribute("aria-label")).toMatch(/Đang nghẽn: CTOR/);
    const streams = [...container.querySelectorAll('#nam-luong ul[aria-label="Năm luồng truy cập"] li')];
    expect(streams.map((li) => li.textContent)).toEqual([
      expect.stringContaining("Thẻ sản phẩm"),
      expect.stringContaining("Tab cửa hàng"),
      expect.stringContaining("Video"),
      expect.stringContaining("LIVE"),
      expect.stringContaining("Liên kết"),
    ]);
    unmount();
  });

  it("Đề xuất & thực thi: Duyệt → Thực thi → Hoàn tác", () => {
    const { container, unmount } = render(<DeXuatPage />);
    const steps = container.querySelectorAll('ol[aria-label="Từ thẻ đề xuất đến thay đổi trên shop"] > li');
    expect([...steps].map((li) => li.textContent)).toEqual([
      expect.stringContaining("Duyệt"),
      expect.stringContaining("Thực thi"),
      expect.stringContaining("Hoàn tác"),
    ]);
    unmount();
  });

  it("Đo lường: Trước → Ngày 7 → Ngày 14", () => {
    const { container, unmount } = render(<DoLuongPage />);
    const steps = container.querySelectorAll('ol[aria-label="Lịch đo một thay đổi"] > li');
    expect([...steps].map((li) => li.textContent)).toEqual([
      expect.stringContaining("Trước khi áp dụng"),
      expect.stringContaining("Ngày 7"),
      expect.stringContaining("Ngày 14"),
    ]);
    unmount();
  });
});

describe("D60 product copy (D13, D34, D45)", () => {
  it("Đề xuất & thực thi: no AOV lever, and the cover is replaced only with the seller's photo", () => {
    const { container, unmount } = render(<DeXuatPage />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/mua nhiều giảm nhiều/i);
    expect(text).not.toMatch(/Với tiêu đề, mô tả và ảnh bìa, Juli/);
    expect(text.replace(/\s+/g, " ")).toContain(
      "Với ảnh bìa, Juli chỉ thay bằng ảnh do bạn gửi, sau khi bạn xác nhận, và giữ ảnh cũ để hoàn tác.",
    );
    unmount();
  });

  it.each([
    ["/san-pham/do-luong-gmv", DoLuongPage],
    ["/san-pham", SanPhamPage],
    ["/", LandingPage],
  ] as const)("%s: no control-group claim", (_name, Page) => {
    const { container, unmount } = render(<Page />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/đối chứng|tương tự (chưa|không) (thay )?đổi|chưa được thay đổi/i);
    expect(text).not.toMatch(/mua nhiều giảm nhiều/i);
    unmount();
  });
});
