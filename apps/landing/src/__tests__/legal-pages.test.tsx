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
    // Identity: Google sign-in, no password, no phone required.
    expect(screen.getByText(/đăng nhập với google là cách duy nhất/i)).toBeInTheDocument();
    // Write path: default-off, sandbox-only today, owner-authorized per listing.
    expect(
      screen.getByText(/không thay đổi bất kỳ điều gì trên shop tiktok shop thật/i),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/sandbox/i).length).toBeGreaterThan(0);
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

  it("renders /terms with the entity, the trial terms, and GMV figures framed as targets", () => {
    render(<TermsOfServicePage />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Điều khoản dịch vụ" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText(new RegExp(COMPANY.name)).length).toBeGreaterThan(0);
    expect(screen.getByText(/miễn phí trong 3 tháng đầu/i)).toBeInTheDocument();
    expect(screen.getByText(/không phải cam kết về kết quả/i)).toBeInTheDocument();
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
