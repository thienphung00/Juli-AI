import { cleanup, render } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AboutPage from "../app/about/page";
import BlogIndexPage from "../app/blog/page";
import BlogPostPage from "../app/blog/[slug]/page";
import ContactPage from "../app/contact/page";
import SignupThanksPage from "../app/dang-ky/cam-on/page";
import SignupPage from "../app/dang-ky/page";
import TikTokShopPage from "../app/ket-noi/tiktok-shop/page";
import LandingPage from "../app/page";
import PrivacyPage from "../app/privacy/page";
import ActionsPage from "../app/san-pham/de-xuat-va-thuc-thi/page";
import MeasurementPage from "../app/san-pham/do-luong-gmv/page";
import ProductPage from "../app/san-pham/page";
import AnalysisPage from "../app/san-pham/phan-tich-shop/page";
import TermsPage from "../app/terms/page";
import { BLOG_POSTS } from "../content/blog";

vi.mock("@juli/tiktok-events", () => ({
  loadTikTokPixel: vi.fn(),
  trackTikTokEvent: vi.fn(),
  TikTokEvents: { completeRegistration: "CompleteRegistration" },
}));

afterEach(cleanup);

/**
 * Heading outline guard for every public page (D45.6; the built-HTML twin is
 * in `seo-check/built-site.check.ts`): exactly one H1 and it comes first, no
 * skipped level (H2 → H4), no empty heading, and no heading inside the site
 * header (incl. the "Sản phẩm" dropdown), any nav, or the footer.
 */
const PAGES: Array<[string, () => ReactElement | Promise<ReactElement>]> = [
  ["/", () => <LandingPage />],
  ["/san-pham", () => <ProductPage />],
  ["/san-pham/phan-tich-shop", () => <AnalysisPage />],
  ["/san-pham/de-xuat-va-thuc-thi", () => <ActionsPage />],
  ["/san-pham/do-luong-gmv", () => <MeasurementPage />],
  ["/ket-noi/tiktok-shop", () => <TikTokShopPage />],
  ["/about", () => <AboutPage />],
  ["/contact", () => <ContactPage />],
  ["/dang-ky", () => <SignupPage />],
  ["/dang-ky/cam-on", () => <SignupThanksPage />],
  ["/blog", () => <BlogIndexPage />],
  ...BLOG_POSTS.map(
    (post) =>
      [`/blog/${post.slug}`, () => BlogPostPage({ params: Promise.resolve({ slug: post.slug }) })] as [
        string,
        () => Promise<ReactElement>,
      ],
  ),
  ["/privacy", () => <PrivacyPage />],
  ["/terms", () => <TermsPage />],
];

describe("heading outline of every public page", () => {
  for (const [path, page] of PAGES) {
    it(path, async () => {
      const { container } = render(await page());
      const headings = [...container.querySelectorAll("h1, h2, h3, h4, h5, h6")].map((node) => ({
        level: Number(node.tagName[1]),
        text: (node.textContent ?? "").trim(),
      }));
      expect(headings.filter((h) => h.level === 1), "exactly one h1").toHaveLength(1);
      expect(headings[0]?.level, "the first heading is the h1").toBe(1);
      headings.forEach((heading, index) => {
        expect(heading.text, `empty h${heading.level}`).not.toBe("");
        if (index === 0) return;
        const previous = headings[index - 1]!;
        expect(
          heading.level,
          `"${previous.text.slice(0, 50)}" (h${previous.level}) → "${heading.text.slice(0, 50)}" (h${heading.level})`,
        ).toBeLessThanOrEqual(previous.level + 1);
      });
      expect(
        container.querySelectorAll(
          ".ui-header :is(h1, h2, h3, h4, h5, h6), nav :is(h1, h2, h3, h4, h5, h6), .ui-footer :is(h1, h2, h3, h4, h5, h6)",
        ),
        "heading inside header / nav / footer",
      ).toHaveLength(0);
    });
  }
});
