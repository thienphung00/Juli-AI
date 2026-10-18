import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AboutPage from "../app/about/page";
import ContactPage from "../app/contact/page";
import LandingPage from "../app/page";
import ProductPage from "../app/san-pham/page";
import { getRoute } from "../lib/seo";
import { COMPANY, DEMO_URL, PRODUCT_PAGES, SIGNUP_URL, SITE_PAGES } from "../lib/site";

// TikTok's developer review (ticket 4486401) requires business content about
// the product and the company that is reachable without logging in.
describe("public product and company pages", () => {
  it("links /san-pham, /about and /contact from every page's header and footer", () => {
    for (const Page of [LandingPage, ProductPage, AboutPage, ContactPage]) {
      const { unmount } = render(<Page />);
      // D44 header: Sản phẩm · Kết nối TikTok Shop · Blog · Giới thiệu; /contact
      // is in the mobile menu and the footer. "Sản phẩm" is a dropdown (D46.1)
      // whose first link, "Tổng quan sản phẩm", is /san-pham.
      const header = screen.getByRole("banner");
      for (const page of SITE_PAGES) {
        const name = page.href === "/san-pham" ? /^Tổng quan sản phẩm/ : page.label;
        expect(
          within(header)
            .getAllByRole("link", { name })
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

  it("/san-pham hero (D46.2): copy + one framed sample-data shot, not prioritised, not repeated", () => {
    const { container } = render(<ProductPage />);
    const hero = container.querySelector('section[aria-labelledby="product-heading"]') as HTMLElement;
    const figure = hero.querySelector("figure.ui-shot") as HTMLElement;
    expect(figure).not.toBeNull();
    expect(figure.querySelector("figcaption")).toHaveTextContent("Dữ liệu mẫu");
    const img = figure.querySelector("img") as HTMLImageElement;
    expect(img.getAttribute("alt")).toMatch(/\(dữ liệu mẫu\)$/);
    expect(img).toHaveAttribute("loading", "lazy");
    expect(img.getAttribute("fetchpriority") ?? "auto").not.toBe("high");
    // The H1 and both CTAs sit next to the shot, in the same hero.
    expect(within(hero).getByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(within(hero).getByTestId("product-trial-cta")).toBeInTheDocument();
    // The hero capture appears once on the page.
    const file = (img.getAttribute("src") ?? "").replace(/-v\d+-\d+\.\w+$/, "");
    const uses = [...container.querySelectorAll("img")].filter((node) =>
      (node.getAttribute("src") ?? "").startsWith(file),
    );
    expect(uses, file).toHaveLength(1);
  });

  it("/san-pham loop (D46.3): five compact steps with icons, short lines, claims kept", () => {
    render(<ProductPage />);
    const section = screen.getByRole("region", { name: "Vòng làm việc của Juli" });
    const list = section.querySelector("ol.ui-steps--stepper") as HTMLElement;
    const steps = [...list.querySelectorAll(":scope > li")];
    expect(steps.map((step) => step.querySelector(".ui-step__title")?.textContent)).toEqual([
      "Phân tích",
      "Đề xuất",
      "Duyệt",
      "Thực thi",
      "Đo lường",
    ]);
    for (const step of steps) {
      expect(step.querySelector(".ui-step__icon svg")).not.toBeNull();
      // One short line: ≤ 18 syllables (Vietnamese words are 1–2 syllables, so ≈ 15 words or fewer).
      const body = step.querySelector(".ui-step__body")?.textContent ?? "";
      expect(body.split(/\s+/).filter((w) => /\p{L}/u.test(w)).length, body).toBeLessThanOrEqual(18);
    }
    const text = list.textContent ?? "";
    for (const claim of [
      "GMV = Lượt hiển thị × CTR × CTOR × AOV",
      "Mỗi ngày vài đề xuất mới",
      "từ chối kèm lý do",
      "API chính thức",
      "lưu giá trị cũ",
      "Giá, khuyến mãi và video",
      "ngày 7",
      "ngày 14",
      "hoàn tác",
    ]) {
      expect(text, claim).toContain(claim);
    }
  });

  it("positioning (D46.7): Juli is for TMĐT sellers, TikTok Shop is the platform connected today", () => {
    for (const path of ["/", "/san-pham"]) {
      const route = getRoute(path);
      expect(route.title, path).toMatch(/TMĐT/);
      expect(route.title, path).toMatch(/TikTok Shop/);
    }
    const { container } = render(<ProductPage />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("phần mềm AI vận hành TMĐT");
    expect(screen.getByRole("main")).toHaveTextContent("hiện Juli kết nối TikTok Shop và đang tích hợp Shopee");
    expect(within(screen.getByRole("contentinfo")).getByText("Trợ lý AI vận hành cho nhà bán TMĐT.")).toBeInTheDocument();
    // No marketplace Juli is not integrating with.
    expect(container.textContent ?? "").not.toMatch(/Lazada|Tiki\b|Sendo/);
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

  it("/about (D44): bird mark, the company card with every fact, and the demo / contact CTAs", () => {
    render(<AboutPage />);
    const card = screen.getByTestId("about-company-card");
    expect(card.querySelector("img.ui-bird")).not.toBeNull();
    for (const value of [COMPANY.name, COMPANY.taxId, COMPANY.address, COMPANY.email, "app-juli.com"]) {
      expect(card, value).toHaveTextContent(value);
    }
    expect(screen.getByTestId("about-demo-cta")).toHaveAttribute("href", DEMO_URL);
    expect(screen.getByTestId("about-contact-cta")).toHaveAttribute("href", "/contact");
  });

  it("/contact (D44): icon cards, and disconnecting a shop means asking the Juli team (D43 additions 3)", () => {
    render(<ContactPage />);
    for (const id of ["contact-email", "contact-address"]) {
      expect(screen.getByTestId(id).querySelector("svg"), id).not.toBeNull();
    }
    const main = screen.getByRole("main");
    expect(main).toHaveTextContent(/Để ngắt kết nối shop, bạn gửi email và đội ngũ Juli sẽ ngắt kết nối giúp bạn/);
    expect(main).not.toHaveTextContent(/Seller Center/);
    expect(screen.getByTestId("contact-demo-cta")).toHaveAttribute("href", DEMO_URL);
  });
});
