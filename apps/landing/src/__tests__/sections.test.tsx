import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CAPABILITY_ROWS, HOME_FAQ } from "../components/home/home-content";
import { SiteHeader } from "../components/ui/site-header";
import LandingPage from "../app/page";
import { HERO_VIDEO } from "../lib/media";
import { PRODUCT_PAGES } from "../lib/site";

/** Homepage = company + product overview (D43.2), laid out to the D44 mockups (P34-B). */
describe("homepage (D43.2 + D44)", () => {
  it("states the service in one H1 and keeps H1 → H2 → H3 without skipping a level", () => {
    const { container } = render(<LandingPage />);

    const h1s = screen.getAllByRole("heading", { level: 1 });
    expect(h1s).toHaveLength(1);
    // Owner's wording (D46.5); "TikTok Shop" stays in the home <title> and meta description.
    expect(h1s[0]).toHaveTextContent(
      "Trợ lý AI vận hành TMĐT: tìm chỗ cải thiện GMV, đề xuất chiến lược, đo kết quả.",
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

  it("hero shot: phones get the card-header crop, lazy, captioned (AC-35.5: the H1 stays the LCP)", () => {
    const { container } = render(<LandingPage />);
    const hero = container.querySelector('section[aria-labelledby="hero-heading"]') as HTMLElement;
    const source = hero.querySelector('source[media][srcset*="cap-dx-the-m-v4-720"]');
    expect(source).not.toBeNull();
    expect(source).toHaveAttribute("width", "720");
    expect(source).toHaveAttribute("height", "212");
    const img = source?.closest("picture")?.querySelector("img") as HTMLImageElement;
    expect(img).toHaveAttribute("loading", "lazy");
    expect(img.getAttribute("fetchpriority") ?? "auto").not.toBe("high");
    expect(img.closest("figure")?.textContent).toContain("Dữ liệu mẫu");
  });

  it("has the Main.dc.html sections, in order", () => {
    render(<LandingPage />);

    const h2s = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    // "Sàn Juli kết nối" is the marketplace strip's label, not a heading (D46.6).
    const strip = screen.getByRole("region", { name: "Sàn Juli kết nối" });
    expect(strip.querySelector("h1, h2, h3, h4, h5, h6")).toBeNull();
    expect(within(strip).getByRole("list", { name: "Sàn Juli kết nối" })).toBeInTheDocument();
    expect(h2s).toEqual([
      "Năm bước, và bạn luôn là người quyết định.",
      CAPABILITY_ROWS.analysis.title,
      CAPABILITY_ROWS.actions.title,
      CAPABILITY_ROWS.measurement.title,
      "Shop là của bạn. Juli chỉ đọc những gì cần và chỉ làm khi bạn đồng ý.",
      "Cho người bán và những đội vận hành shop.",
      "Minh bạch thay cho lời quảng cáo",
      "Dùng thử miễn phí 3 tháng.",
      "Câu hỏi thường gặp",
    ]);
    for (const step of ["Phân tích", "Đề xuất", "Duyệt", "Thực thi", "Đo lường"]) {
      expect(screen.getByRole("heading", { level: 3, name: step })).toBeInTheDocument();
    }
    // Every section is a named landmark (aria-labelledby → its heading).
    for (const name of h2s) {
      expect(screen.getByRole("region", { name: name! })).toBeInTheDocument();
    }
  });

  it("names TikTok Shop as live via the Open API and Shopee only as being integrated (D42.6)", () => {
    render(<LandingPage />);

    const tiktok = screen.getByTestId("market-tiktok");
    expect(within(tiktok).getByText("Đang hoạt động")).toHaveAttribute("data-status", "live");
    expect(tiktok).toHaveTextContent("TikTok Shop Open API");
    const shopee = screen.getByTestId("market-shopee");
    expect(within(shopee).getByText("Đang tích hợp")).toHaveAttribute("data-status", "integrating");
    expect(shopee).toHaveTextContent("qua Shopee Open Platform");
    expect(shopee).not.toHaveTextContent("Đang hoạt động");
    // The FAQ says it plainly too.
    expect(screen.getByText(/Chưa\. Juli đang tích hợp qua Shopee Open Platform/)).toBeInTheDocument();
    expect(screen.queryByText(/TikTok Shop Partner/)).not.toBeInTheDocument();
    expect(screen.queryByText(/sắp ra mắt/i)).not.toBeInTheDocument();
  });

  it("links each capability row to its product page", () => {
    render(<LandingPage />);

    for (const key of ["analysis", "actions", "measurement"] as const) {
      const link = screen.getByTestId(`capability-link-${key}`);
      expect(link, key).toHaveAttribute("href", PRODUCT_PAGES[key].href);
      expect(link, key).toHaveTextContent(`Xem ${PRODUCT_PAGES[key].label}`);
    }
  });

  it("shows real product screenshots, each labelled as sample data (D44.3)", () => {
    const { container } = render(<LandingPage />);

    const shots = [...container.querySelectorAll("main img")].filter((img) =>
      img.getAttribute("src")?.startsWith("/media/cap-"),
    );
    expect(shots.length).toBeGreaterThanOrEqual(5);
    for (const img of shots) {
      expect(img.getAttribute("alt"), img.getAttribute("src")!).toMatch(/\(dữ liệu mẫu\)$/);
      expect(img).toHaveAttribute("width");
      expect(img).toHaveAttribute("height");
    }
    // The hero shot is NOT prioritised: on mobile the H1 is the LCP, and an
    // eager or high-priority hero image competes with the fonts it waits on
    // (local Lighthouse mobile A/B, P34 AC-34.7: LCP 3.4 s eager vs 2.5 s lazy;
    // desktop stays 98).
    expect(shots[0]).toHaveAttribute("loading", "lazy");
    expect(shots[0]).toHaveAttribute("fetchpriority", "auto");
    // No mascot with baked-in figures, no sales-video frame with numbers.
    expect(container.querySelector('img[src*="hero-mascot"]')).toBeNull();
  });

  it("claims only what Juli executes (D13, D24.5): listings yes; price and promotions stay the seller's", () => {
    const { container } = render(<LandingPage />);
    const text = container.textContent ?? "";

    expect(text).toContain("Juli thực thi: tiêu đề, mô tả, thuộc tính sản phẩm");
    expect(text).toContain("Giá và khuyến mãi: Juli đề xuất, bạn làm trong Seller Center");
    expect(text).toContain("Ảnh bìa: Juli đề xuất, chỉ tải lên khi bạn cung cấp ảnh");
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

  it("names the operating company with its tax id, address and email", () => {
    render(<LandingPage />);

    const company = screen.getByTestId("home-company");
    expect(company.tagName).toBe("DL");
    expect(company).toHaveTextContent("Công ty TNHH Công Nghệ Juli AI");
    expect(company).toHaveTextContent("0319617654");
    expect(company).toHaveTextContent("1B Đường số 30 Trần Não");
    expect(within(company).getByRole("link", { name: "lienhe@app-juli.com" })).toHaveAttribute(
      "href",
      "mailto:lienhe@app-juli.com",
    );
  });

  it("renders every FAQ question that goes into FAQPage, and 5–8 of them", () => {
    render(<LandingPage />);

    expect(HOME_FAQ.length).toBeGreaterThanOrEqual(5);
    expect(HOME_FAQ.length).toBeLessThanOrEqual(8);
    for (const item of HOME_FAQ) {
      expect(screen.getByText(item.question)).toBeInTheDocument();
      expect(screen.getByText(item.answer)).toBeInTheDocument();
    }
  });

  it("emits VideoObject and exactly one FAQPage JSON-LD, for exactly the shown FAQ", () => {
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
    const faqs = nodes.filter((node) => node["@type"] === "FAQPage") as {
      mainEntity: { name: string }[];
    }[];
    expect(faqs).toHaveLength(1);
    expect(faqs[0]!.mainEntity.map((q) => q.name)).toEqual(HOME_FAQ.map((q) => q.question));
  });
});

describe("hero video (D43.6): 'Xem video 1 phút' opens it on demand", () => {
  it("renders a play button and no <video> until clicked", () => {
    const { container } = render(<LandingPage />);

    expect(screen.queryByTestId("hero-demo-video")).toBeNull();
    expect(container.querySelector("video")).toBeNull();
    const play = screen.getByTestId("hero-video-play");
    expect(play.tagName).toBe("BUTTON");
    expect(play).toHaveTextContent("Xem video 1 phút");
    expect(play).toHaveAttribute("aria-haspopup", "dialog");
  });

  it("mounts the video in a dialog with preload=none only after the click, then plays it", () => {
    render(<LandingPage />);

    fireEvent.click(screen.getByTestId("hero-video-play"));
    const dialog = screen.getByTestId("hero-video-dialog");
    expect(dialog).toHaveAttribute("open");
    expect(dialog).toHaveAccessibleName("Video giới thiệu Juli (1:04)");
    const video = within(dialog).getByTestId("hero-demo-video");
    expect(video).toHaveAttribute("src", "/videos/juli-demo.mp4");
    expect(video).toHaveAttribute("preload", "none");
    expect(video).toHaveAttribute("controls");
    expect(video).toHaveAttribute("poster", HERO_VIDEO.poster.large.webp);
    expect(video).toHaveProperty("autoplay", true);
  });

  it("labels the figures inside the video as illustrative", () => {
    render(<LandingPage />);

    fireEvent.click(screen.getByTestId("hero-video-play"));
    expect(screen.getByText(/Số liệu trong video là minh hoạ/)).toBeInTheDocument();
  });

  it("unmounts the video again when the dialog closes", () => {
    render(<LandingPage />);

    fireEvent.click(screen.getByTestId("hero-video-play"));
    const dialog = screen.getByTestId("hero-video-dialog");
    fireEvent(dialog, new Event("close"));
    expect(screen.queryByTestId("hero-demo-video")).toBeNull();
  });
});

describe("site header", () => {
  it("links the public pages in order, on desktop and in the mobile menu", () => {
    render(<SiteHeader />);
    for (const name of ["Điều hướng chính", "Menu trên điện thoại"]) {
      const nav = screen.getByRole("navigation", { name });
      // "Sản phẩm" is a dropdown button (D46.1) whose links lead the list.
      expect(within(nav).getByRole("button", { name: "Sản phẩm" }), name).toBeInTheDocument();
      const labels = within(nav)
        .getAllByRole("link")
        .map((link) => link.querySelector(".ui-navmenu__label")?.textContent ?? link.textContent);
      expect(labels, name).toEqual([
        "Tổng quan sản phẩm",
        "Phân tích shop",
        "Đề xuất và thực thi",
        "Đo lường GMV",
        "Kết nối TikTok Shop",
        "Blog",
        "Giới thiệu",
      ]);
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
