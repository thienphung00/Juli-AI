import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import GmvCalculatorPage from "../app/cong-cu/tinh-gmv/page";
import { parseMarkdown } from "../components/blog/markdown";
import {
  calculateFromCounts,
  calculateFromRates,
  equalUplifts,
  formatPercent,
  formatVietnameseNumber,
  formatVnd,
  gmvWithFactor,
  parseVietnameseNumber,
  relativeChange,
  type CountInputs,
} from "../components/gmv-calculator/calc";
import {
  EXAMPLE_NOTE,
  GMV_POST_ANCHORS,
  GMV_POST_SLUG,
  PRIVACY_LINE,
  STEP_GUIDES,
  TOOL_FAQ,
  TOOL_H1,
  TOOL_LEAD,
  TOOL_PATH,
} from "../components/gmv-calculator/content";
import { GmvCalculator } from "../components/gmv-calculator/gmv-calculator";
import { gmvPostHref } from "../components/gmv-calculator/post-href";
import { BLOG_POSTS, getPost } from "../content/blog";
import { absoluteUrl, getRoute, llmsTxt, sitemapEntries, SITE_ROUTES, TITLE_MAX_LENGTH } from "../lib/seo";
import { FOOTER_PRODUCT_LINKS, PRODUCT_MENU } from "../lib/site";

afterEach(() => {
  vi.restoreAllMocks();
});

/* ————— Pure maths ————— */

describe("parseVietnameseNumber", () => {
  it.each([
    ["50.000", 50000],
    ["1.250.000", 1250000],
    ["180000", 180000],
    ["3,5", 3.5],
    ["3.5", 3.5],
    ["0,25", 0.25],
    ["1.234,5", 1234.5],
    ["1,250,000", 1250000],
    ["10 800 000 ₫", 10800000],
    ["180.000đ", 180000],
    ["3 %", 3],
    [" 50.000 ", 50000],
    ["0", 0],
    [",5", 0.5],
  ])("reads %j as %d", (raw, value) => {
    expect(parseVietnameseNumber(raw)).toEqual({ ok: true, value });
  });

  it("reads one dot followed by three digits as thousands, as Vietnamese sellers write", () => {
    expect(parseVietnameseNumber("1.500")).toEqual({ ok: true, value: 1500 });
  });

  it.each([
    ["", "empty"],
    ["   ", "empty"],
    ["abc", "invalid"],
    ["1.2.3", "invalid"],
    ["1,2,3", "invalid"],
    ["12.34,5,6", "invalid"],
    ["1.23,5", "invalid"],
    ["3,5%x", "invalid"],
    ["-5", "negative"],
    ["−3,5", "negative"],
  ])("rejects %j (%s)", (raw, reason) => {
    expect(parseVietnameseNumber(raw)).toEqual({ ok: false, reason });
  });
});

describe("Vietnamese formatting", () => {
  it("groups thousands with dots and uses a decimal comma", () => {
    expect(formatVietnameseNumber(1234567.891, 2)).toBe("1.234.567,89");
    expect(formatVietnameseNumber(1500)).toBe("1.500");
    expect(formatVietnameseNumber(0)).toBe("0");
    expect(formatVietnameseNumber(999.995, 2)).toBe("1.000");
    expect(formatVietnameseNumber(-0.001, 2)).toBe("0");
  });

  it("rounds half away from zero and drops trailing zeros", () => {
    expect(formatVietnameseNumber(2.5)).toBe("3");
    expect(formatVietnameseNumber(1.005, 2)).toBe("1,01");
    expect(formatVietnameseNumber(3.1, 2)).toBe("3,1");
  });

  it("formats money and percentages", () => {
    expect(formatVnd(10800000)).toBe("10.800.000 ₫");
    expect(formatVnd(12960000.4)).toBe("12.960.000 ₫");
    expect(formatPercent(0.03)).toBe("3 %");
    expect(formatPercent(0.0325)).toBe("3,25 %");
    expect(formatPercent(1 / 3)).toBe("33,33 %");
  });
});

describe("calculateFromRates", () => {
  it("multiplies the four factors (the post's hypothetical example)", () => {
    const result = calculateFromRates({ impressions: "50.000", ctrPercent: "3", ctorPercent: "4", aov: "180.000" });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.funnel).toMatchObject({ impressions: 50000, ctr: 0.03, ctor: 0.04, aov: 180000, zeroFactor: null });
    expect(result.funnel.clicks).toBeCloseTo(1500, 9);
    expect(result.funnel.orders).toBeCloseTo(60, 9);
    expect(result.funnel.gmv).toBeCloseTo(10800000, 4);
    expect(result.funnel.warnings).toEqual([]);
  });

  it("keeps fractional clicks/orders unrounded inside GMV", () => {
    const result = calculateFromRates({ impressions: "1.000", ctrPercent: "3,33", ctorPercent: "5", aov: "100.000" });
    if (!result.ok) throw new Error("expected ok");
    expect(result.funnel.clicks).toBeCloseTo(33.3, 9);
    expect(result.funnel.orders).toBeCloseTo(1.665, 9);
    expect(result.funnel.gmv).toBeCloseTo(166500, 4);
  });

  it("explains every invalid field in Vietnamese", () => {
    const result = calculateFromRates({ impressions: "", ctrPercent: "abc", ctorPercent: "-2", aov: "0" });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.impressions).toBe("Nhập Lượt hiển thị sản phẩm.");
    expect(result.errors.ctrPercent).toMatch(/^CTR chưa đúng định dạng số/);
    expect(result.errors.ctorPercent).toBe("CTOR không thể là số âm.");
    expect(result.errors.aov).toBe("AOV cần lớn hơn 0.");
  });

  it("refuses a CTR above 100 % and fractional impressions", () => {
    const result = calculateFromRates({ impressions: "1.000,5", ctrPercent: "120", ctorPercent: "4", aov: "1" });
    if (result.ok) throw new Error("expected errors");
    expect(result.errors.impressions).toMatch(/số nguyên/);
    expect(result.errors.ctrPercent).toMatch(/không thể quá 100 %/);
  });

  it("flags a zero step as the one blocking GMV, and warns on CTOR above 100 %", () => {
    const zero = calculateFromRates({ impressions: "1.000", ctrPercent: "0", ctorPercent: "4", aov: "1.000" });
    if (!zero.ok) throw new Error("expected ok");
    expect(zero.funnel.gmv).toBe(0);
    expect(zero.funnel.zeroFactor).toBe("ctr");

    const over = calculateFromRates({ impressions: "1.000", ctrPercent: "1", ctorPercent: "150", aov: "1.000" });
    if (!over.ok) throw new Error("expected ok");
    expect(over.funnel.warnings[0]).toMatch(/^CTOR trên 100 %/);
  });
});

describe("calculateFromCounts", () => {
  const base: CountInputs = { impressions: "50.000", clicks: "1.500", orders: "60", money: "gmv", gmv: "10.800.000", aov: "" };

  it("derives CTR, CTOR and AOV from counts and GMV", () => {
    const result = calculateFromCounts(base);
    if (!result.ok) throw new Error("expected ok");
    expect(result.funnel.ctr).toBeCloseTo(0.03, 12);
    expect(result.funnel.ctor).toBeCloseTo(0.04, 12);
    expect(result.funnel.aov).toBeCloseTo(180000, 6);
    expect(result.funnel.gmv).toBe(10800000);
  });

  it("derives GMV from AOV when that is what the seller has", () => {
    const result = calculateFromCounts({ ...base, money: "aov", gmv: "", aov: "180.000" });
    if (!result.ok) throw new Error("expected ok");
    expect(result.funnel.gmv).toBe(10800000);
  });

  it("rejects counts that cannot come from one funnel", () => {
    const more = calculateFromCounts({ ...base, clicks: "60.000" });
    if (more.ok) throw new Error("expected errors");
    expect(more.errors.clicks).toMatch(/không thể nhiều hơn Lượt hiển thị/);

    const noClicks = calculateFromCounts({ ...base, clicks: "0" });
    if (noClicks.ok) throw new Error("expected errors");
    expect(noClicks.errors.orders).toMatch(/cần có Lượt nhấp/);

    const noOrders = calculateFromCounts({ ...base, orders: "0" });
    if (noOrders.ok) throw new Error("expected errors");
    expect(noOrders.errors.gmv).toMatch(/cần có Đơn hàng SKU/);

    const fractional = calculateFromCounts({ ...base, orders: "2,5" });
    if (fractional.ok) throw new Error("expected errors");
    expect(fractional.errors.orders).toMatch(/số nguyên/);

    const zeroImpressions = calculateFromCounts({ ...base, impressions: "0" });
    if (zeroImpressions.ok) throw new Error("expected errors");
    expect(zeroImpressions.errors.impressions).toBe("Lượt hiển thị sản phẩm cần lớn hơn 0.");
  });

  it("leaves undefined rates as null instead of dividing by zero", () => {
    const noClicks = calculateFromCounts({ ...base, clicks: "0", orders: "0", gmv: "0" });
    if (!noClicks.ok) throw new Error("expected ok");
    expect(noClicks.funnel).toMatchObject({ ctr: 0, ctor: null, aov: null, gmv: 0, zeroFactor: "ctr" });

    const noOrders = calculateFromCounts({ ...base, orders: "0", gmv: "0" });
    if (!noOrders.ok) throw new Error("expected ok");
    expect(noOrders.funnel).toMatchObject({ ctor: 0, aov: null, zeroFactor: "ctor" });
    expect(equalUplifts(noOrders.funnel, 10)).toEqual([]);
  });
});

describe("what-if", () => {
  const funnel = (() => {
    const result = calculateFromRates({ impressions: "50.000", ctrPercent: "3", ctorPercent: "4", aov: "180.000" });
    if (!result.ok) throw new Error("expected ok");
    return result.funnel;
  })();

  it("gives the same GMV gain for the same relative improvement on any step", () => {
    const rows = equalUplifts(funnel, 10);
    expect(rows.map((row) => row.factor)).toEqual(["impressions", "ctr", "ctor", "aov"]);
    for (const row of rows) {
      expect(row.gmv).toBeCloseTo(11880000, 3);
      expect(row.gain).toBeCloseTo(1080000, 3);
      expect(row.to / row.from).toBeCloseTo(1.1, 12);
    }
  });

  it("moves one factor and holds the rest (CTR 3 % → 3,6 % is +20 %)", () => {
    const gmv = gmvWithFactor(funnel, "ctr", 0.036);
    expect(gmv).toBeCloseTo(12960000, 3);
    expect(relativeChange(funnel.gmv, gmv!)).toBeCloseTo(0.2, 12);
    expect(relativeChange(0, 100)).toBeNull();
  });
});

/* ————— The component ————— */

describe("<GmvCalculator>", () => {
  it("starts empty: labelled inputs, no prefilled result", () => {
    render(<GmvCalculator postHref={null} />);
    for (const label of ["Lượt hiển thị sản phẩm", "CTR (tỷ lệ nhấp)", "CTOR (tỷ lệ từ nhấp đến đặt hàng)", "AOV (SKU)"]) {
      expect(screen.getByLabelText(label)).toHaveValue("");
    }
    expect(screen.getByTestId("gmv-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("gmv-results")).toBeNull();
    expect(screen.getByTestId("gmv-live")).toHaveAttribute("aria-live", "polite");
  });

  it("explains errors next to the fields and focuses the first one", async () => {
    const user = userEvent.setup();
    render(<GmvCalculator postHref={null} />);
    await user.type(screen.getByLabelText("CTR (tỷ lệ nhấp)"), "abc");
    await user.click(screen.getByRole("button", { name: "Tính GMV" }));
    const impressions = screen.getByLabelText("Lượt hiển thị sản phẩm");
    expect(impressions).toHaveAttribute("aria-invalid", "true");
    expect(impressions).toHaveAccessibleDescription(/Nhập Lượt hiển thị sản phẩm\./);
    expect(screen.getByLabelText("CTR (tỷ lệ nhấp)")).toHaveAccessibleDescription(/chưa đúng định dạng số/);
    expect(screen.getByTestId("gmv-live")).toHaveTextContent("Chưa tính được: 4 ô cần sửa.");
    await vi.waitFor(() => expect(impressions).toHaveFocus());
  });

  it("calculates from typed values, shows the funnel, equal uplifts and step questions, and sends nothing", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const user = userEvent.setup();
    render(<GmvCalculator postHref={null} />);
    await user.type(screen.getByLabelText("Lượt hiển thị sản phẩm"), "50.000");
    await user.type(screen.getByLabelText("CTR (tỷ lệ nhấp)"), "3");
    await user.type(screen.getByLabelText("CTOR (tỷ lệ từ nhấp đến đặt hàng)"), "4");
    await user.type(screen.getByLabelText("AOV (SKU)"), "180.000");
    await user.click(screen.getByRole("button", { name: "Tính GMV" }));

    expect(screen.getByTestId("gmv-total")).toHaveTextContent("10.800.000 ₫");
    expect(screen.getByTestId("gmv-live")).toHaveTextContent("GMV: 10.800.000 ₫");
    const funnel = within(screen.getByTestId("gmv-funnel"));
    expect(funnel.getByRole("row", { name: /Lượt nhấp CTR 3 % 1\.500/ })).toBeInTheDocument();
    expect(funnel.getByRole("row", { name: /Đơn hàng SKU CTOR 4 % 60/ })).toBeInTheDocument();
    // Not prefilled example output: no example label.
    expect(screen.queryByText(EXAMPLE_NOTE)).toBeNull();

    const uplifts = within(screen.getByTestId("gmv-uplifts")).getAllByRole("row").slice(1);
    expect(uplifts).toHaveLength(4);
    for (const row of uplifts) expect(row).toHaveTextContent("11.880.000 ₫ (+1.080.000 ₫)");

    // Honest "weakest step": no benchmark, a question per step.
    expect(screen.getByTestId("gmv-weakest")).toHaveTextContent(/không thể nói CTR 3 % là thấp hay cao/);
    expect(within(screen.getByTestId("gmv-guides")).getAllByRole("heading", { level: 4 }).map((h) => h.textContent)).toEqual(
      STEP_GUIDES.map((guide) => guide.question),
    );
    // The blog post is a draft: no link to it.
    expect(within(screen.getByTestId("gmv-results")).queryAllByRole("link")).toHaveLength(0);

    // Changing the uplift updates every row equally.
    const uplift = screen.getByLabelText("Mức tăng thử cho mỗi bước");
    await user.clear(uplift);
    await user.type(uplift, "20");
    for (const row of within(screen.getByTestId("gmv-uplifts")).getAllByRole("row").slice(1)) {
      expect(row).toHaveTextContent("12.960.000 ₫ (+2.160.000 ₫)");
    }

    // A specific what-if: CTR 3 % → 3,6 %.
    await user.type(screen.getByLabelText("Giá trị mới (%)"), "3,6");
    expect(screen.getByTestId("gmv-whatif")).toHaveTextContent(
      "Nếu CTR đổi từ 3 % thành 3,6 %, GMV đổi từ 10.800.000 ₫ thành 12.960.000 ₫ (+20 %).",
    );

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(setItem).not.toHaveBeenCalled();
  });

  it("fills a labelled hypothetical example on request, and clears it", async () => {
    const user = userEvent.setup();
    render(<GmvCalculator postHref={null} />);
    await user.click(screen.getByRole("button", { name: "Thử ví dụ giả định" }));
    expect(screen.getByLabelText("Lượt hiển thị sản phẩm")).toHaveValue("50.000");
    expect(screen.getByText(EXAMPLE_NOTE)).toBeInTheDocument();
    expect(screen.getByTestId("gmv-total")).toHaveTextContent("10.800.000 ₫");
    await user.click(screen.getByRole("button", { name: "Xoá số liệu" }));
    expect(screen.getByLabelText("Lượt hiển thị sản phẩm")).toHaveValue("");
    expect(screen.getByTestId("gmv-empty")).toBeInTheDocument();
  });

  it("derives the rates in count mode, and names a zero step as the blocker", async () => {
    const user = userEvent.setup();
    render(<GmvCalculator postHref={null} />);
    await user.click(screen.getByRole("radio", { name: "Số đếm: lượt nhấp, đơn hàng" }));
    await user.type(screen.getByLabelText("Lượt hiển thị sản phẩm"), "40.000");
    await user.type(screen.getByLabelText("Lượt nhấp vào sản phẩm"), "1.200");
    await user.type(screen.getByLabelText("Đơn hàng SKU"), "40");
    await user.type(screen.getByLabelText("GMV"), "7.200.000");
    await user.click(screen.getByRole("button", { name: "Tính GMV" }));
    const funnel = within(screen.getByTestId("gmv-funnel"));
    expect(funnel.getByRole("row", { name: /CTR 3 %/ })).toBeInTheDocument();
    expect(funnel.getByRole("row", { name: /CTOR 3,33 %/ })).toBeInTheDocument();
    expect(funnel.getByRole("row", { name: /AOV 180\.000 ₫/ })).toBeInTheDocument();

    const orders = screen.getByLabelText("Đơn hàng SKU");
    await user.clear(orders);
    await user.type(orders, "0");
    const gmv = screen.getByLabelText("GMV");
    await user.clear(gmv);
    await user.type(gmv, "0");
    await user.click(screen.getByRole("button", { name: "Tính GMV" }));
    expect(screen.getByTestId("gmv-zero")).toHaveTextContent("GMV đang bằng 0 vì CTOR bằng 0");
    expect(within(screen.getByTestId("gmv-funnel")).getByText(/AOV chưa tính được/)).toBeInTheDocument();
  });

  it("links each step to its section of the post once the post is published", async () => {
    const user = userEvent.setup();
    render(<GmvCalculator postHref="/blog/gmv-la-gi-tiktok-shop" />);
    await user.click(screen.getByRole("button", { name: "Thử ví dụ giả định" }));
    const hrefs = within(screen.getByTestId("gmv-guides"))
      .getAllByRole("link")
      .map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual([
      "/blog/gmv-la-gi-tiktok-shop#tang-luot-hien-thi-san-pham",
      "/blog/gmv-la-gi-tiktok-shop#tang-ctr",
      "/blog/gmv-la-gi-tiktok-shop#tang-ctor",
      "/blog/gmv-la-gi-tiktok-shop#tang-aov",
    ]);
  });
});

/* ————— The page ————— */

describe("/cong-cu/tinh-gmv page", () => {
  it("has one H1, the lead, the privacy line, and the outline", () => {
    const { container } = render(<GmvCalculatorPage />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(TOOL_H1);
    expect(screen.getByText(TOOL_LEAD)).toBeInTheDocument();
    expect(screen.getByTestId("tool-privacy")).toHaveTextContent(PRIVACY_LINE);
    const h2 = [...container.querySelectorAll("main h2")].map((h) => h.textContent);
    expect(h2).toEqual([
      "Tính GMV của bạn",
      "Cách đọc kết quả",
      "Câu hỏi thường gặp",
      "Muốn biết GMV hụt ở luồng nào, sản phẩm nào?",
    ]);
    for (const faq of TOOL_FAQ) expect(screen.getByText(faq.question)).toBeInTheDocument();
  });

  it("keeps the heading order intact once results are shown", async () => {
    const user = userEvent.setup();
    const { container } = render(<GmvCalculatorPage />);
    await user.click(screen.getByRole("button", { name: "Thử ví dụ giả định" }));
    const levels = [...container.querySelectorAll("h1, h2, h3, h4, h5, h6")].map((h) => Number(h.tagName[1]));
    expect(levels.filter((level) => level === 1)).toHaveLength(1);
    expect(levels[0]).toBe(1);
    levels.forEach((level, i) => {
      if (i > 0) expect(level).toBeLessThanOrEqual(levels[i - 1]! + 1);
    });
    expect(levels).toContain(4);
  });

  it("emits WebPage, BreadcrumbList and FAQPage, never an app type or a rating", () => {
    const { container } = render(<GmvCalculatorPage />);
    const scripts = [...container.querySelectorAll('script[type="application/ld+json"]')].map((s) => s.textContent ?? "");
    const json = scripts.join("\n");
    const graph = scripts.flatMap((text) => {
      const parsed = JSON.parse(text) as { "@graph"?: Array<{ "@type": string }> } & { "@type"?: string };
      return parsed["@graph"] ?? [parsed as { "@type": string }];
    });
    expect(graph.map((node) => node["@type"]).sort()).toEqual(["BreadcrumbList", "FAQPage", "WebPage"]);
    expect(json).not.toMatch(/WebApplication|SoftwareApplication|aggregateRating|"review"/);
  });

  it("links the analysis page and one soft trial CTA; the draft post only as plain text", () => {
    render(<GmvCalculatorPage />);
    const main = screen.getByRole("main");
    const hrefs = within(main)
      .getAllByRole("link")
      .map((a) => a.getAttribute("href") ?? "");
    expect(hrefs).toContain("/san-pham/phan-tich-shop");
    expect(hrefs.filter((href) => href === "/dang-ky")).toHaveLength(1);
    const post = BLOG_POSTS.find((p) => p.slug === GMV_POST_SLUG)!;
    if (post.status === "draft") {
      expect(hrefs.some((href) => href.startsWith(`/blog/${GMV_POST_SLUG}`))).toBe(false);
      expect(within(main).getByText(/GMV là gì\? Cách tính và cách tăng GMV TikTok Shop/)).toBeInTheDocument();
    }
  });

  it("uses no em dash in visible copy (D46.4)", () => {
    const { container } = render(<GmvCalculatorPage />);
    expect(container.querySelector("main")?.textContent).not.toContain("—");
    const strings = [TOOL_H1, TOOL_LEAD, PRIVACY_LINE, EXAMPLE_NOTE, ...TOOL_FAQ.flatMap((f) => [f.question, f.answer]),
      ...STEP_GUIDES.flatMap((g) => [g.question, ...g.look])];
    for (const text of strings) expect(text).not.toContain("—");
  });
});

describe("the GMV post link", () => {
  it("points at the post only when it is published", () => {
    const draft = BLOG_POSTS.map((p) => (p.slug === GMV_POST_SLUG ? { ...p, status: "draft" as const } : p));
    const published = BLOG_POSTS.map((p) => (p.slug === GMV_POST_SLUG ? { ...p, status: "published" as const } : p));
    expect(gmvPostHref(draft)).toBeNull();
    expect(gmvPostHref(published)).toBe("/blog/gmv-la-gi-tiktok-shop");
  });

  it("targets headings that exist in the post", () => {
    const body = getPost(GMV_POST_SLUG)?.body ?? "";
    const ids = parseMarkdown(body).flatMap((block) => (block.kind === "h2" || block.kind === "h3" ? [block.id] : []));
    for (const anchor of Object.values(GMV_POST_ANCHORS)) expect(ids, anchor).toContain(anchor);
  });
});

describe("route, sitemap, llms.txt and navigation", () => {
  it("is registered, indexable, sized, in the sitemap and in /llms.txt", () => {
    const route = getRoute(TOOL_PATH);
    expect(route.noindex).toBeFalsy();
    expect(route.title).toBe("Công cụ tính GMV TikTok Shop miễn phí | Juli AI");
    expect(route.title.length).toBeLessThanOrEqual(TITLE_MAX_LENGTH);
    expect(route.description.length).toBeGreaterThanOrEqual(70);
    expect(route.description.length).toBeLessThanOrEqual(155);
    expect(route.description).not.toContain("—");
    expect(sitemapEntries(SITE_ROUTES).map((entry) => entry.url)).toContain(absoluteUrl(TOOL_PATH));
    const text = llmsTxt(SITE_ROUTES);
    expect(text).toContain(
      `## Công cụ miễn phí\n\n- [Công cụ tính GMV TikTok Shop miễn phí](${absoluteUrl(TOOL_PATH)}): ${route.description}`,
    );
  });

  it("is in the footer, not in the header's product dropdown (D46.1)", () => {
    expect(FOOTER_PRODUCT_LINKS.map((link) => link.href)).toContain(TOOL_PATH);
    expect(PRODUCT_MENU.map((item) => item.href as string)).not.toContain(TOOL_PATH);
  });
});
