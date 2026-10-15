import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HOME_FAQ } from "../components/home/home-content";
import { LandingHeader } from "../components/landing-header";
import LandingPage from "../app/page";
import { HERO_VIDEO } from "../lib/media";
import { PRODUCT_PAGES } from "../lib/site";

/** Homepage = company + product overview (D43.2, AC-33.5, P33-B). */
describe("homepage (D43.2)", () => {
  it("states the service in one H1 and keeps H1 → H2 → H3 without skipping a level", () => {
    const { container } = render(<LandingPage />);

    const h1s = screen.getAllByRole("heading", { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent(
      "Juli AI — trợ lý AI vận hành cho nhà bán TikTok Shop: phân tích, đề xuất, thực thi sau khi bạn duyệt, đo GMV",
    );
    const levels = [...container.querySelectorAll("h1, h2, h3, h4, h5, h6")].map((h) =>
      Number(h.tagName[1]),
    );
    expect(levels[0]).toBe(1);
    levels.forEach((level, i) => {
      if (i > 0) expect(level).toBeLessThanOrEqual(levels[i - 1]! + 1);
    });
    expect(levels.some((level) => level > 3)).toBe(false);
  });

  it("has the D43.2 sections, in order", () => {
    render(<LandingPage />);

    const h2s = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(h2s).toEqual([
      "Sàn thương mại điện tử Juli kết nối",
      "GMV giảm, nhưng hụt ở đâu?",
      "Juli làm việc thế nào: Phân tích → Đề xuất → Duyệt → Thực thi → Đo lường",
      "Ba năng lực chính của Juli",
      "Dữ liệu an toàn, quyền quyết định là của bạn",
      "Juli dành cho ai",
      "Minh bạch thay cho lời quảng cáo",
      "Chi phí: dùng thử miễn phí 3 tháng, sau đó từ 500K/tháng",
      "Câu hỏi thường gặp",
      "Xem shop của bạn đang hụt GMV ở đâu",
    ]);
    for (const step of ["Phân tích", "Đề xuất", "Duyệt", "Thực thi", "Đo lường"]) {
      expect(screen.getByRole("heading", { level: 3, name: step })).toBeInTheDocument();
    }
  });

  it("names TikTok Shop as live via the Open API and Shopee only as being integrated (D42.6)", () => {
    render(<LandingPage />);

    const tiktok = screen.getByTestId("market-tiktok");
    expect(tiktok).toHaveTextContent("Đang hoạt động");
    expect(tiktok).toHaveTextContent("TikTok Shop Open API");
    const shopee = screen.getByTestId("market-shopee");
    expect(shopee).toHaveTextContent("đang tích hợp qua Shopee Open Platform");
    expect(shopee).toHaveTextContent("Hiện chưa kết nối được shop Shopee");
    expect(shopee).not.toHaveTextContent("Đang hoạt động");
    expect(screen.queryByText(/TikTok Shop Partner/)).not.toBeInTheDocument();
    expect(screen.queryByText(/sắp ra mắt/i)).not.toBeInTheDocument();
  });

  it("links each capability block to its product page", () => {
    render(<LandingPage />);

    expect(screen.getByTestId("capability-link-analysis")).toHaveAttribute(
      "href",
      PRODUCT_PAGES.analysis.href,
    );
    expect(screen.getByTestId("capability-link-actions")).toHaveAttribute(
      "href",
      PRODUCT_PAGES.actions.href,
    );
    expect(screen.getByTestId("capability-link-measurement")).toHaveAttribute(
      "href",
      PRODUCT_PAGES.measurement.href,
    );
  });

  it("claims only what Juli executes (D13, D24.5): listings yes; price and promotions stay the seller's", () => {
    const { container } = render(<LandingPage />);
    const text = container.textContent ?? "";

    expect(text).toContain("Juli thực thi: tiêu đề, mô tả, thuộc tính sản phẩm");
    expect(text).toContain("Giá và khuyến mãi: Juli đề xuất, bạn làm trong Seller Center");
    // The old copy promised things Juli does not do.
    expect(text).not.toMatch(/tạo đơn nhập|đồng bộ tồn kho|tạo mã giảm giá/i);
  });

  it("shows no testimonial, case study or outcome figure (D43.3)", () => {
    const { container } = render(<LandingPage />);
    const text = container.textContent ?? "";

    expect(text).not.toMatch(/1–3%|1-3%|5–10%|1,7 giờ|29 giờ|ROI cao/);
    expect(text).not.toMatch(/khách hàng nói|đánh giá của khách|case study/i);
    // Every percentage on the page would need a source; there are none.
    expect(text).not.toMatch(/\d\s?%/);
  });

  it("names the operating company with its tax id and address", () => {
    render(<LandingPage />);

    const company = screen.getByTestId("home-company");
    expect(company).toHaveTextContent("Công ty TNHH Công Nghệ Juli AI");
    expect(company).toHaveTextContent("0319617654");
    expect(company).toHaveTextContent("1B Đường số 30 Trần Não");
  });

  it("renders every FAQ question that goes into FAQPage, and 5–8 of them", () => {
    render(<LandingPage />);

    expect(HOME_FAQ.length).toBeGreaterThanOrEqual(5);
    expect(HOME_FAQ.length).toBeLessThanOrEqual(8);
    for (const item of HOME_FAQ) {
      expect(screen.getByText(item.question)).toBeInTheDocument();
    }
  });

  it("emits VideoObject and FAQPage JSON-LD for exactly the shown FAQ", () => {
    const { container } = render(<LandingPage />);

    const nodes = [...container.querySelectorAll('script[type="application/ld+json"]')].flatMap(
      (script) => {
        const parsed = JSON.parse(script.textContent ?? "{}") as Record<string, unknown>;
        return (parsed["@graph"] as Record<string, unknown>[] | undefined) ?? [parsed];
      },
    );
    const video = nodes.find((node) => node["@type"] === "VideoObject");
    expect(video).toMatchObject({
      contentUrl: "https://app-juli.com/videos/juli-demo.mp4",
      duration: "PT1M4S",
    });
    const faq = nodes.find((node) => node["@type"] === "FAQPage") as {
      mainEntity: { name: string }[];
    };
    expect(faq.mainEntity.map((q) => q.name)).toEqual(HOME_FAQ.map((q) => q.question));
  });
});

describe("hero video (D43.6)", () => {
  it("shows a sized AVIF/WebP poster with a play button and no <video> until clicked", () => {
    const { container } = render(<LandingPage />);

    expect(screen.queryByTestId("hero-demo-video")).toBeNull();
    expect(container.querySelector("video")).toBeNull();
    const play = screen.getByTestId("hero-video-play");
    expect(play).toHaveAccessibleName(/Phát video giới thiệu Juli/);
    const img = within(play).getByRole("img");
    expect(img).toHaveAttribute("width", String(HERO_VIDEO.poster.large.width));
    expect(img).toHaveAttribute("height", String(HERO_VIDEO.poster.large.height));
    expect(img).toHaveAttribute("src", "/media/home-demo-poster-v1-1280.webp");
    expect(img).toHaveAttribute("fetchpriority", "high");
    expect(play.querySelector('source[type="image/avif"]')).not.toBeNull();
  });

  it("mounts the video with preload=none only after the click, then plays it", () => {
    render(<LandingPage />);

    fireEvent.click(screen.getByTestId("hero-video-play"));
    const video = screen.getByTestId("hero-demo-video");
    expect(video).toHaveAttribute("src", "/videos/juli-demo.mp4");
    expect(video).toHaveAttribute("preload", "none");
    expect(video).toHaveAttribute("controls");
    expect(video).toHaveAttribute("poster", "/media/home-demo-poster-v1-1280.webp");
    expect(video).toHaveProperty("autoplay", true);
    expect(screen.queryByTestId("hero-video-play")).toBeNull();
  });

  it("labels the figures inside the video as illustrative", () => {
    render(<LandingPage />);

    expect(screen.getByText(/Số liệu trong video là minh hoạ/)).toBeInTheDocument();
  });
});

describe("site header", () => {
  it("links the public pages in order, on desktop and in the mobile menu", () => {
    render(<LandingHeader />);
    for (const name of ["Điều hướng chính", "Menu trên điện thoại"]) {
      const labels = within(screen.getByRole("navigation", { name }))
        .getAllByRole("link")
        .map((link) => link.textContent);
      expect(labels, name).toEqual(["Sản phẩm", "Blog", "Giới thiệu", "Liên hệ"]);
    }
  });

  it("serves one DOM for all breakpoints — layout adapts via CSS only", () => {
    render(<LandingPage />);

    expect(screen.getByRole("navigation", { name: "Điều hướng chính" })).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });
});

describe("site footer", () => {
  it("links the overview, the three capability pages, the TikTok Shop page, blog and company pages", () => {
    render(<LandingPage />);

    const footer = screen.getByRole("contentinfo");
    const hrefs = within(footer)
      .getAllByRole("link")
      .map((link) => link.getAttribute("href"));
    for (const href of [
      "/san-pham",
      "/san-pham/phan-tich-shop",
      "/san-pham/de-xuat-va-thuc-thi",
      "/san-pham/do-luong-gmv",
      "/ket-noi/tiktok-shop",
      "/blog",
      "/about",
      "/contact",
      "/privacy",
      "/terms",
      "mailto:lienhe@app-juli.com",
    ]) {
      expect(hrefs, href).toContain(href);
    }
    expect(within(footer).getByText("© 2026 Công ty TNHH Công Nghệ Juli AI")).toBeInTheDocument();
  });

  it("has no social links (D43.8)", () => {
    render(<LandingPage />);

    const hrefs = within(screen.getByRole("contentinfo"))
      .getAllByRole("link")
      .map((link) => link.getAttribute("href") ?? "");
    expect(hrefs.join(" ")).not.toMatch(/facebook|tiktok\.com|youtube|zalo|linkedin|instagram/i);
  });
});

describe("owner decisions 2026-10-15 (D43 additions)", () => {
  it("disconnecting goes through the Juli team, never 'revoke in Seller Center'", () => {
    const { container } = render(<LandingPage />);
    const text = container.textContent ?? "";

    expect(text).toContain("bạn liên hệ Juli qua email hoặc trang Liên hệ; đội Juli ngắt kết nối");
    expect(text).not.toMatch(/thu hồi quyền/);
  });

  it("states the free trial the way /terms §5 does", () => {
    render(<LandingPage />);

    expect(
      screen.getAllByText(/dùng thử miễn phí 3 tháng kể từ ngày đăng ký, không cần thẻ thanh toán/).length,
    ).toBeGreaterThanOrEqual(1);
  });
});
