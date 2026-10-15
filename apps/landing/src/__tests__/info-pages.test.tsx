import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AboutPage from "../app/about/page";
import ContactPage from "../app/contact/page";
import LandingPage from "../app/page";
import ProductPage from "../app/san-pham/page";
import { COMPANY, DEMO_URL, PRODUCT_PAGES, SIGNUP_URL, SITE_PAGES } from "../lib/site";

// TikTok's developer review (ticket 4486401) requires business content about
// the product and the company that is reachable without logging in.
describe("public product and company pages", () => {
  it("links /san-pham, /about and /contact from every page's header and footer", () => {
    for (const Page of [LandingPage, ProductPage, AboutPage, ContactPage]) {
      const { unmount } = render(<Page />);
      // D44 header: Sản phẩm · Kết nối TikTok Shop · Blog · Giới thiệu; /contact
      // is in the mobile menu and the footer.
      const header = screen.getByRole("banner");
      for (const page of SITE_PAGES) {
        expect(
          within(header)
            .getAllByRole("link", { name: page.label })
            .map((link) => link.getAttribute("href")),
          page.href,
        ).toContain(page.href);
        // The footer's "Sản phẩm" column links /san-pham as "Tổng quan sản phẩm".
        const footerHrefs = within(screen.getByRole("contentinfo"))
          .getAllByRole("link")
          .map((link) => link.getAttribute("href"));
        expect(footerHrefs, page.href).toContain(page.href);
      }
      unmount();
    }
  });

  it("shows the operating entity in the footer of every page", () => {
    for (const Page of [LandingPage, ProductPage, AboutPage, ContactPage]) {
      const { unmount } = render(<Page />);
      const company = screen.getByTestId("footer-company");
      expect(company).toHaveTextContent(COMPANY.name);
      expect(company).toHaveTextContent(COMPANY.taxId);
      expect(company).toHaveTextContent(COMPANY.address);
      unmount();
    }
  });

  it("/san-pham describes the product, its TikTok Shop data use, pricing and FAQ", () => {
    render(<ProductPage />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/Juli AI/);
    for (const name of [
      "Juli AI là gì",
      "Ba năng lực chính",
      "Kết nối và tích hợp",
      "Dữ liệu và quyền kiểm soát",
      "Bảng giá",
      "Câu hỏi thường gặp",
    ]) {
      expect(screen.getByRole("heading", { level: 2, name }), name).toBeInTheDocument();
    }
    // Pricing matches /terms section 5.
    expect(screen.getByTestId("product-pricing")).toHaveTextContent("500.000đ/tháng");
    expect(screen.getByTestId("product-demo-cta")).toHaveAttribute("href", DEMO_URL);
    for (const testId of ["product-trial-cta", "product-pricing-trial-cta", "product-final-trial-cta"]) {
      expect(screen.getByTestId(testId), testId).toHaveAttribute("href", SIGNUP_URL);
      expect(screen.getByTestId(testId), testId).toHaveTextContent("Dùng thử miễn phí 3 tháng");
    }
    expect(screen.getByRole("main")).not.toHaveTextContent(/thu hồi quyền/);
  });

  it("/san-pham (AC-34.3) links each capability page, marks Shopee only as Đang tích hợp, FAQ = FAQPage", () => {
    const { container } = render(<ProductPage />);
    const main = screen.getByRole("main");
    const hrefs = within(main)
      .getAllByRole("link")
      .map((link) => link.getAttribute("href"));
    for (const page of Object.values(PRODUCT_PAGES)) expect(hrefs, page.href).toContain(page.href);
    // The five-step loop, "Duyệt" marked as the seller's step.
    const steps = main.querySelectorAll(".ui-steps > li");
    expect(steps).toHaveLength(5);
    expect(main.querySelector(".ui-step--you")).toHaveTextContent("Duyệt");
    // Integrations: TikTok Shop live, Shopee integrating — and Shopee never next to "hoạt động".
    expect(main.querySelector('[data-status="live"]')?.closest(".ui-card")).toHaveTextContent("TikTok Shop");
    expect(main.querySelector('[data-status="integrating"]')?.closest(".ui-card")).toHaveTextContent("Shopee");
    const text = main.textContent ?? "";
    for (const match of text.matchAll(/Shopee/g)) {
      const around = text.slice(Math.max(0, (match.index ?? 0) - 40), (match.index ?? 0) + 80);
      expect(around).toMatch(/tích hợp|Chính sách bảo mật|Juli sẽ dùng|chưa kết nối/i);
    }
    // One FAQ source: the questions shown are exactly the FAQPage JSON-LD.
    const node = container.querySelector('script[type="application/ld+json"]');
    const graph = (JSON.parse(node?.textContent ?? "{}")["@graph"] ?? []) as Array<Record<string, unknown>>;
    const faq = graph.find((entity) => entity["@type"] === "FAQPage");
    const questions = (faq?.mainEntity as Array<{ name: string }>).map((q) => q.name);
    expect([...main.querySelectorAll(".ui-faq summary")].map((q) => q.textContent)).toEqual(questions);
    expect(container.querySelectorAll(".ui-section--dark")).toHaveLength(1);
  });

  it("/about names the company with its legal details", () => {
    render(<AboutPage />);

    expect(screen.getByRole("heading", { level: 1, name: "Về Juli AI" })).toBeInTheDocument();
    for (const value of [COMPANY.name, COMPANY.taxId, COMPANY.address, COMPANY.email]) {
      expect(screen.getAllByText(value).length, value).toBeGreaterThan(0);
    }
  });

  it("/contact gives an email link and the registered address", () => {
    render(<ContactPage />);

    expect(within(screen.getByTestId("contact-email")).getByRole("link")).toHaveAttribute(
      "href",
      `mailto:${COMPANY.email}`,
    );
    expect(screen.getByTestId("contact-address")).toHaveTextContent(COMPANY.address);
  });

  it("publishes no placeholder or coming-soon copy on any public page", () => {
    for (const Page of [LandingPage, ProductPage, AboutPage, ContactPage]) {
      const { container, unmount } = render(<Page />);
      expect(container).not.toHaveTextContent(/sắp ra mắt|coming soon|lorem|TODO/i);
      unmount();
    }
  });
});
