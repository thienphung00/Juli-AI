import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AboutPage from "../app/about/page";
import ContactPage from "../app/contact/page";
import LandingPage from "../app/page";
import ProductPage from "../app/san-pham/page";
import { COMPANY, DEMO_URL, SITE_PAGES } from "../lib/site";

// TikTok's developer review (ticket 4486401) requires business content about
// the product and the company that is reachable without logging in.
describe("public product and company pages", () => {
  it("links /san-pham, /about and /contact from every page's header and footer", () => {
    for (const Page of [LandingPage, ProductPage, AboutPage, ContactPage]) {
      const { unmount } = render(<Page />);
      const header = screen.getByRole("navigation", { name: "Điều hướng chính" });
      for (const page of SITE_PAGES) {
        expect(within(header).getByRole("link", { name: page.label })).toHaveAttribute(
          "href",
          page.href,
        );
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
