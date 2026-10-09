import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LandingPage from "../app/page";

describe("landing sections (PRD 2.7)", () => {
  it("renders the hero with GMV-led heading, promise triplet, hook, reassurance line, and partner badge", () => {
    render(<LandingPage />);

    expect(
      screen.getByText("Chi phí vận hành và hoa hồng sàn ngày càng tăng?"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /tăng trưởng GMV ổn định — mở rộng mà không cần đổ thêm ngân sách/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Shopee · sắp ra mắt")).toBeInTheDocument();
    // Hero badge + footer both carry the partner line.
    expect(screen.getAllByText(/TikTok Shop Partner/).length).toBeGreaterThanOrEqual(1);
    // The outcome triplet is three separate lines, not one run-on sentence.
    for (const promise of [
      "Hướng đến +1–3% GMV mỗi tháng",
      "Tiết kiệm ~1,7 giờ/ngày mỗi nhân sự",
      "Mở rộng tinh gọn, ROI cao (chi phí từ 500K)",
    ]) {
      expect(screen.getByText(promise)).toBeInTheDocument();
    }
    expect(
      screen.getByText(/đăng nhập ngay để biết chính xác 3 điều shop bạn cần cải thiện/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/miễn phí thử nghiệm 3 tháng · dành cho điện thoại/i),
    ).toBeInTheDocument();
  });

  it("shows the sales demo video in the hero, loaded only on play", () => {
    render(<LandingPage />);

    const video = screen.getByTestId("hero-demo-video");
    expect(video).toHaveAttribute("src", "/videos/juli-demo.mp4");
    expect(video).toHaveAttribute("poster", "/videos/juli-demo-poster.jpg");
    expect(video).toHaveAttribute("preload", "none");
    expect(video).toHaveAttribute("controls");
    expect(video).not.toHaveAttribute("autoplay");
  });

  it("renders the four-step story strip", () => {
    render(<LandingPage />);

    expect(
      screen.getByRole("region", { name: "Juli làm việc như thế nào" }),
    ).toBeInTheDocument();
    for (const label of ["Phân tích", "Gợi ý", "Thực hiện", "Theo dõi"]) {
      // Each label appears in the strip and again as a feature card title.
      expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(2);
    }
  });

  it("renders the market comparison with Juli highlighted between the two alternatives", () => {
    render(<LandingPage />);

    expect(
      screen.getByRole("heading", { name: "Giải pháp trên thị trường" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Tự vận hành")).toBeInTheDocument();
    expect(screen.getByText("→ Juli ←")).toBeInTheDocument();
    expect(screen.getByText("Thuê Agency")).toBeInTheDocument();
    expect(screen.getByText("Không thay thế người bán")).toBeInTheDocument();
  });

  it("renders feature cards with code-rebuilt mockup content (no flattened bitmaps)", () => {
    render(<LandingPage />);

    expect(screen.getByText("Sức khỏe tồn kho")).toBeInTheDocument();
    expect(screen.getByText(/dự báo doanh thu/i)).toBeInTheDocument();
    expect(screen.getByText("Bổ sung tồn kho kịp thời")).toBeInTheDocument();
    expect(screen.getByText("Tạo đơn nhập kho tự động")).toBeInTheDocument();
    expect(screen.getByText("Đẩy khuyến mãi mùa hè")).toBeInTheDocument();
  });

  it("renders the closing trial CTA section", () => {
    render(<LandingPage />);

    expect(
      screen.getByRole("heading", {
        name: "Tăng trưởng tinh gọn và ổn định, bắt đầu miễn phí.",
      }),
    ).toBeInTheDocument();
  });

  it("renders the footer with brand lockup and contact link", () => {
    render(<LandingPage />);

    const footer = screen.getByRole("contentinfo");
    expect(within(footer).getByText("© 2026 Juli AI")).toBeInTheDocument();
    expect(
      within(footer).getByRole("link", { name: "lienhe@app-juli.com" }),
    ).toHaveAttribute("href", "mailto:lienhe@app-juli.com");
  });

  it("serves one DOM for all breakpoints — layout adapts via CSS only (PRD story 6)", () => {
    // jsdom applies no media queries; everything the mobile viewport shows must
    // already be in this single render, and nothing may branch on matchMedia.
    render(<LandingPage />);

    expect(screen.getByRole("navigation", { name: "Điều hướng chính" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
    // Full section census — identical content regardless of viewport.
    expect(screen.getByText("Giải pháp trên thị trường")).toBeInTheDocument();
    expect(
      screen.getByText(/tối ưu từng luồng truy cập, từ thẻ sản phẩm đến live/i),
    ).toBeInTheDocument();
  });
});
