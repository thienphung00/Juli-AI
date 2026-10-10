import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LandingPage from "../app/page";
import PrivacyPolicyPage from "../app/privacy/page";
import TermsOfServicePage from "../app/terms/page";
import { COMPANY } from "../lib/site";

describe("privacy and terms pages exist and are linked (issue #1971)", () => {
  it("renders /privacy with a heading, last-updated line, and the operating entity", () => {
    render(<PrivacyPolicyPage />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Chính sách bảo mật" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/cập nhật lần cuối/i)).toBeInTheDocument();
    expect(screen.getAllByText(new RegExp(COMPANY.taxId)).length).toBeGreaterThan(0);
  });

  it("grounds /privacy's data sections in what the code actually reads and writes", () => {
    render(<PrivacyPolicyPage />);

    // Read scope — the poll's actual resources (workers/services/polling): each
    // resource word appears in more than one section, so assert against the
    // read-scope bullet list specifically rather than a page-wide text query.
    const list = screen.getByRole("list", { name: "Dữ liệu shop Juli đọc" });
    const items = within(list)
      .getAllByRole("listitem")
      .map((item) => item.textContent ?? "");
    for (const resource of ["Đơn hàng", "Sản phẩm", "Tồn kho", "Đơn hoàn"]) {
      expect(items.some((text) => text.includes(resource)), resource).toBe(true);
    }
    // Identity: Google or email-code sign-in, no password.
    expect(screen.getByText(/đăng nhập với google, hoặc bằng\s+email/i)).toBeInTheDocument();
    // Write path: default-off, sandbox-only today, owner-authorized per listing.
    expect(
      screen.getByText(/không thay đổi bất kỳ điều gì trên shop tiktok shop thật/i),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/sandbox/i).length).toBeGreaterThan(0);
  });

  describe("Google OAuth brand verification: /privacy §3 covers every item Google checks", () => {
    function googleSection() {
      render(<PrivacyPolicyPage />);
      const heading = screen.getByRole("heading", {
        level: 2,
        name: /Dữ liệu người dùng Google \(Google user data\)/,
      });
      const section = heading.closest("section");
      expect(section).not.toBeNull();
      return section as HTMLElement;
    }

    it("has a dedicated, deep-linkable section naming the brand, the operator and the scopes", () => {
      const section = googleSection();
      expect(section).toHaveAttribute("id", "du-lieu-nguoi-dung-google");
      expect(section).toHaveTextContent("Juli AI");
      expect(section).toHaveTextContent("app-juli.com");
      expect(section).toHaveTextContent(COMPANY.name);
      // Exactly the scopes the Supabase Google door requests — nothing else.
      expect(section).toHaveTextContent(/openid, email và profile/);
      expect(section).toHaveTextContent(/không yêu cầu quyền truy cập Gmail, Google\s+Drive/);
    });

    it("states WHAT Google user data is accessed", () => {
      googleSection();
      const list = screen.getByRole("list", { name: "Dữ liệu người dùng Google Juli truy cập" });
      for (const field of ["email", "Tên hiển thị", "Ảnh đại diện", "Google account ID"]) {
        expect(list, field).toHaveTextContent(field);
      }
    });

    it("states HOW it is used, with the no-ads / no-sale / no-AI-training limits", () => {
      const section = googleSection();
      const list = screen.getByRole("list", { name: "Cách Juli sử dụng dữ liệu người dùng Google" });
      expect(list).toHaveTextContent(/Tạo tài khoản Juli/);
      expect(list).toHaveTextContent(/Liên hệ với bạn về tài khoản/);
      expect(section).toHaveTextContent(/cho quảng cáo/);
      expect(section).toHaveTextContent(/không\s*bán dữ liệu này/);
      expect(section).toHaveTextContent(/huấn luyện các mô hình trí tuệ nhân tạo \(AI\) hoặc học máy \(ML\) tổng quát/);
    });

    it("affirms compliance with the Google API Services User Data Policy, including Limited Use", () => {
      const section = googleSection();
      const links = within(section)
        .getAllByRole("link", { name: /Google API Services/ })
        .map((link) => link.getAttribute("href"));
      expect(links).toContain("https://developers.google.com/terms/api-services-user-data-policy");
      expect(section).toHaveTextContent(/Limited Use/);
    });

    it("states WITH WHOM it is shared: service providers, the law, consent — never sold, never to ad platforms", () => {
      const section = googleSection();
      const list = screen.getByRole("list", { name: "Bên nhận dữ liệu người dùng Google" });
      expect(list).toHaveTextContent("Supabase");
      expect(list).toHaveTextContent(/pháp luật/);
      expect(list).toHaveTextContent(/sự đồng ý/);
      expect(section).toHaveTextContent(/không bán, không cho thuê/);
      expect(section).toHaveTextContent(/không gửi dữ liệu người dùng Google cho nền tảng quảng cáo/);
      // The TikTok processor bullet must not claim an (even hashed) email is sent.
      expect(screen.getByRole("list", { name: "Bên xử lý dữ liệu" })).toHaveTextContent(
        /không nhận email/,
      );
    });

    it("describes the data protection mechanisms", () => {
      googleSection();
      const list = screen.getByRole("list", { name: "Cách Juli bảo vệ dữ liệu người dùng Google" });
      expect(list).toHaveTextContent(/TLS/);
      expect(list).toHaveTextContent(/encryption at rest/);
      expect(list).toHaveTextContent(/row-level\s+security/);
      expect(list).toHaveTextContent(/không lưu mã\s+truy cập Google/);
    });

    it("states retention, how to request deletion and its timeframe, and how to revoke access", () => {
      const section = googleSection();
      const list = screen.getByRole("list", { name: "Lưu trữ và xoá dữ liệu người dùng Google" });
      expect(list).toHaveTextContent(/tài\s+khoản Juli của bạn còn tồn tại/);
      expect(list).toHaveTextContent(/trong vòng 30 ngày/);
      expect(within(list).getByRole("link", { name: COMPANY.email })).toHaveAttribute(
        "href",
        `mailto:${COMPANY.email}`,
      );
      expect(within(list).getByRole("link", { name: /quyền của tài khoản Google/ })).toHaveAttribute(
        "href",
        "https://myaccount.google.com/permissions",
      );
      expect(section).toHaveTextContent(/myaccount\.google\.com\/permissions/);
    });

    it("drops the short English summary from the Vietnamese §3 (the full English version replaces it)", () => {
      const section = googleSection();
      expect(section.querySelector('[lang="en"]')).toBeNull();
    });
  });

  describe("Google OAuth brand verification: /privacy has a complete English version on the same URL", () => {
    function englishPart() {
      const { container } = render(<PrivacyPolicyPage />);
      const part = container.querySelector("#english");
      expect(part).not.toBeNull();
      return part as HTMLElement;
    }

    it("is a separate, anchored part with lang=\"en\" and its own heading", () => {
      const part = englishPart();
      expect(part).toHaveAttribute("lang", "en");
      expect(
        within(part).getByRole("heading", { level: 2, name: "Privacy Policy — Juli AI (English)" }),
      ).toBeInTheDocument();
    });

    it("is linked from the top of the page with \"English version ↓\"", () => {
      render(<PrivacyPolicyPage />);
      expect(screen.getByRole("link", { name: "English version ↓" })).toHaveAttribute(
        "href",
        "#english",
      );
    });

    it("states app name, operator, tax ID, website, contact and date in English near the top", () => {
      render(<PrivacyPolicyPage />);
      const notice = screen.getByTestId("privacy-en-notice");
      expect(notice).toHaveAttribute("lang", "en");
      expect(notice).toHaveTextContent("App name: Juli AI");
      expect(notice).toHaveTextContent(COMPANY.name);
      expect(notice).toHaveTextContent(`tax ID ${COMPANY.taxId}`);
      expect(notice).toHaveTextContent("Website: app-juli.com");
      expect(notice).toHaveTextContent(COMPANY.email);
      expect(notice).toHaveTextContent(/Last updated \(effective date\): October 10, 2026/);
    });

    it("translates every section 1–12", () => {
      const part = englishPart();
      const headings = within(part)
        .getAllByRole("heading", { level: 3 })
        .map((heading) => heading.textContent);
      expect(headings).toEqual([
        "1. Who we are",
        "2. Account information",
        "3. Google user data",
        "4. Information we read from your shop",
        "5. What Juli records or changes on your shop",
        "6. Purposes of data use",
        "7. Who we share data with",
        "8. Security and retention",
        "9. Your rights",
        "10. Age requirement",
        "11. Changes to this policy",
        "12. Contact",
      ]);
    });

    it("gives Google user data a first-class section with every required subsection", () => {
      const part = englishPart();
      const section = within(part)
        .getByRole("heading", { level: 3, name: "3. Google user data" })
        .closest("section") as HTMLElement;
      expect(section).toHaveAttribute("id", "google-user-data");
      expect(section).toHaveTextContent(/openid, email and profile/);
      const subheadings = within(section)
        .getAllByRole("heading", { level: 4 })
        .map((heading) => heading.textContent);
      expect(subheadings).toEqual([
        "3.1. Data Juli accesses",
        "3.2. How Juli uses this data",
        "3.3. Limited Use",
        "3.4. Who Juli shares this data with",
        "3.5. How Juli protects this data",
        "3.6. Retention, deletion and revoking access",
      ]);
      expect(section).toHaveTextContent(
        "Juli AI’s use and transfer to any other app of information received from Google APIs will adhere to the Google API Services User Data Policy (https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.",
      );
      expect(
        within(section).getByRole("link", { name: "Google API Services User Data Policy" }),
      ).toHaveAttribute("href", "https://developers.google.com/terms/api-services-user-data-policy");
      for (const phrase of [
        "does not use this data for advertising",
        "does not sell this data",
        "generalized artificial intelligence (AI) or machine learning (ML) models",
        "does not sell, rent or trade Google user data",
        "encrypted at rest",
        "row-level security",
        "within 30 days",
        "myaccount.google.com/permissions",
      ]) {
        expect(section, phrase).toHaveTextContent(phrase);
      }
      expect(within(section).getByRole("link", { name: COMPANY.email })).toHaveAttribute(
        "href",
        `mailto:${COMPANY.email}`,
      );
    });

    it("says in both languages that the Vietnamese version prevails, except over Limited Use", () => {
      const part = englishPart();
      expect(part).toHaveTextContent(/the Vietnamese version prevails, except where/);
      expect(part).toHaveTextContent(/Limited Use requirements \(section 3\), which always apply/);
      expect(screen.getByText(/bản\s+tiếng Việt được ưu tiên áp dụng/)).toBeInTheDocument();
    });
  });

  it("names every data processor the product actually sends data to, including the LLM", () => {
    render(<PrivacyPolicyPage />);

    const list = screen.getByRole("list", { name: "Bên xử lý dữ liệu" });
    for (const processor of ["Supabase", "TikTok Shop API", "OpenAI", "Zalo", "Firebase", "TikTok Pixel"]) {
      expect(list, processor).toHaveTextContent(processor);
    }
    expect(screen.getByText(/không bán dữ liệu của bạn/i)).toBeInTheDocument();
  });

  it("publishes no unfinished drafts: no placeholders, no 'pending legal review' banner", () => {
    for (const Page of [PrivacyPolicyPage, TermsOfServicePage]) {
      const { container, unmount } = render(<Page />);
      expect(container).not.toHaveTextContent(/\[OWNER:/);
      expect(container).not.toHaveTextContent(/bộ phận pháp lý/i);
      unmount();
    }
  });

  it("renders /terms with the entity, the fee terms, and AI suggestions run only on consent", () => {
    render(<TermsOfServicePage />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Điều khoản dịch vụ" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText(new RegExp(COMPANY.name)).length).toBeGreaterThan(0);
    expect(screen.getByText(/500\.000đ\/tháng.*huỷ bất cứ lúc nào/i)).toBeInTheDocument();
    expect(screen.getByText(/chỉ thực hiện một hành động khi bạn đồng ý/i)).toBeInTheDocument();
    expect(screen.queryByText(/GMV/)).not.toBeInTheDocument();
  });

  it("/terms links back to /privacy for the data-handling detail", () => {
    render(<TermsOfServicePage />);

    const privacyLinks = screen
      .getAllByRole("link")
      .filter((link) => link.getAttribute("href") === "/privacy");
    expect(privacyLinks.length).toBeGreaterThan(0);
  });

  it("neither legal page repeats the home page's in-page section nav (its anchors don't exist there)", () => {
    render(<PrivacyPolicyPage />);
    expect(screen.queryByRole("navigation", { name: "Điều hướng chính" })).not.toBeInTheDocument();
    // The brand + Demo CTA still render.
    expect(screen.getByRole("link", { name: "Juli AI, trang chủ" })).toBeInTheDocument();
    expect(screen.getByTestId("header-demo-cta")).toBeInTheDocument();
  });

  it("links both pages from the footer, present on every landing page", () => {
    render(<LandingPage />);
    const footer = screen.getByRole("contentinfo");

    expect(within(footer).getByRole("link", { name: "Chính sách bảo mật" })).toHaveAttribute(
      "href",
      "/privacy",
    );
    expect(within(footer).getByRole("link", { name: "Điều khoản dịch vụ" })).toHaveAttribute(
      "href",
      "/terms",
    );
  });

  it("links both pages from the landing's own sign-in surface (the hero login/signup CTA)", () => {
    render(<LandingPage />);

    const note = screen.getByTestId("hero-consent-note");
    expect(within(note).getByRole("link", { name: "Điều khoản dịch vụ" })).toHaveAttribute(
      "href",
      "/terms",
    );
    expect(within(note).getByRole("link", { name: "Chính sách bảo mật" })).toHaveAttribute(
      "href",
      "/privacy",
    );
  });
});
