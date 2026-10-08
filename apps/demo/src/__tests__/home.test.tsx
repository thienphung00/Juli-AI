import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import HomePage from "../app/page";
import { DemoStateProvider } from "../components/demo-state";
import { HomeOverview } from "../components/home/home-overview";
import { ENTRY_MODE_STORAGE_KEY } from "../lib/entry-mode";
import sampleEnvelope from "../lib/shop-analysis/sample-report.json";
import type { ShopAnalysisEnvelope } from "../lib/shop-analysis/types";
import { ACTIVE_SHOP_STORAGE_KEY } from "../lib/shop-session";
import { buildHomeOverview, windowLengthDays } from "../lib/shop-report/home-metrics";
import { ShopReportProvider } from "../lib/shop-report/shop-report-context";
import { AUTH_SESSION_STORAGE_KEY } from "../lib/supabase-auth";
import { vnClock, vnWeekdayDate } from "../lib/vn-format";

/**
 * Trang chủ (AC-8.5, ADR-109 decision 3): GMV / Đơn / AOV cards and the
 * 5-stream matrix from the ADR-108 report. Replaces the two-launcher Home
 * (#1319) — ADR-109 puts the report's overview on Home on purpose.
 */

const SAMPLE = sampleEnvelope as unknown as ShopAnalysisEnvelope;

function withoutShopTab(envelope: ShopAnalysisEnvelope): ShopAnalysisEnvelope {
  return {
    ...envelope,
    report: {
      ...envelope.report,
      channels: envelope.report.channels.filter((row) => row.channel !== "shop_tab"),
    },
  };
}

function renderHome(loadAnalysis?: () => Promise<ShopAnalysisEnvelope | null>) {
  return render(
    <DemoStateProvider>
      <ShopReportProvider loadAnalysis={loadAnalysis}>
        <HomePage />
      </ShopReportProvider>
    </DemoStateProvider>,
  );
}

describe("home metrics — mapping the ADR-108 report", () => {
  it("turns daily averages into 30-day totals and keeps whole orders when the report has them", () => {
    const model = buildHomeOverview(SAMPLE);
    const { total, windows } = SAMPLE.report;
    const days = windowLengthDays(windows.last_first, windows.last_last);

    expect(days).toBe(30);
    const [gmv, orders, aov] = model.cards;
    expect(gmv.label).toBe("GMV 30 ngày");
    expect(gmv.last).toBeCloseTo(total.last.gmv * 30);
    expect(gmv.prior).toBeCloseTo(total.prior.gmv * 30);
    expect(orders.last).toBe(total.orders_last);
    expect(orders.prior).toBe(total.orders_prior);
    expect(aov.last).toBeCloseTo(total.last.gmv / (total.last.sku_orders as number));
  });

  it("lays out the five streams in the video's three groups, Liên kết monitor-only and unlinked", () => {
    const model = buildHomeOverview(SAMPLE);

    expect(model.groups.map((g) => g.label)).toEqual([
      "Tăng trưởng từ sản phẩm",
      "Tăng trưởng từ nội dung",
      "Tiếp thị liên kết · chỉ theo dõi, Juli không tác động",
    ]);
    expect(model.groups.map((g) => g.rows.map((r) => r.label))).toEqual([
      ["Thẻ sản phẩm", "Tab cửa hàng"],
      ["Video của shop", "LIVE của shop"],
      ["Liên kết"],
    ]);
    const affiliate = model.groups[2].rows[0];
    expect(affiliate.monitorOnly).toBe(true);
    expect(affiliate.cells.every((cell) => cell.href === null)).toBe(true);
    const productCard = model.groups[0].rows[0];
    expect(productCard.cells.map((cell) => cell.href)).toEqual([
      "/analytics?tab=san-pham&stream=the-san-pham&metric=hien-thi",
      "/analytics?tab=san-pham&stream=the-san-pham&metric=ctr",
      "/analytics?tab=san-pham&stream=the-san-pham&metric=ctor",
      "/analytics?tab=san-pham&stream=the-san-pham&metric=aov",
    ]);
    expect(model.groups[1].rows[1].cells[0].href).toBe(
      "/analytics?tab=noi-dung&stream=live&metric=hien-thi",
    );
  });

  it("marks Tab cửa hàng CTOR/AOV as estimated (TikTok gives no SKU orders there)", () => {
    const shopTab = buildHomeOverview(SAMPLE).groups[0].rows[1];
    expect(shopTab.cells.map((cell) => cell.estimated)).toEqual([false, false, true, true]);
  });

  it("treats a missing Tab cửa hàng as missing, never as a stream that sold nothing", () => {
    const shopTab = buildHomeOverview(withoutShopTab(SAMPLE)).groups[0].rows[1];
    expect(shopTab.missing).toBe(true);
    expect(shopTab.cells.every((cell) => cell.last === null && cell.href === null)).toBe(true);
  });

  it("formats the header clock and the eyebrow date in Vietnam time", () => {
    expect(vnClock("2026-10-07T01:15:00+07:00")).toBe("01:15");
    expect(vnClock("2026-10-06T19:05:00Z")).toBe("02:05");
    expect(vnClock("not a date")).toBeNull();
    expect(vnWeekdayDate("2026-10-07T01:15:00+07:00")).toBe("Thứ tư, 07/10");
  });
});

describe("HomeOverview view", () => {
  it("renders the eyebrow, a conclusion h1, the three cards and the matrix", () => {
    render(<HomeOverview envelope={SAMPLE} sample />);

    expect(screen.getByText(/^Trang chủ · Thứ/)).toHaveClass("eyebrow");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      /^GMV 30 ngày (tăng|giảm) .* so với kỳ trước$/,
    );
    expect(screen.getByTestId("home-stat-gmv")).toHaveTextContent("GMV 30 ngày");
    expect(screen.getByTestId("home-stat-orders")).toHaveTextContent("Đơn 30 ngày");
    expect(screen.getByTestId("home-stat-orders")).toHaveTextContent("1.724");
    expect(screen.getByTestId("home-stat-orders")).toHaveTextContent("trước 1.442");
    expect(screen.getByTestId("home-stat-aov")).toHaveTextContent("AOV");
    expect(screen.getByTestId("mock-data-notice")).toHaveTextContent("Dữ liệu mẫu");

    const matrix = screen.getByRole("region", { name: "Ma trận 5 luồng truy cập" });
    const headers = within(matrix).getAllByRole("columnheader").map((th) => th.textContent);
    expect(headers).toEqual(["Luồng truy cập", "Lượt hiển thị sản phẩm/ngày", "CTR", "CTOR", "AOV"]);
    expect(within(matrix).getAllByText(/so với kỳ trước/).length).toBeGreaterThanOrEqual(16);

    const ctrLink = within(matrix).getByRole("link", { name: /^CTR Thẻ sản phẩm:/ });
    expect(ctrLink).toHaveAttribute("href", "/analytics?tab=san-pham&stream=the-san-pham&metric=ctr");
    // Liên kết is shown but never linked: Juli does not act on affiliate.
    expect(within(matrix).queryByRole("link", { name: /Liên kết/ })).toBeNull();
    const affiliateRow = matrix.querySelector('tr[data-channel="affiliate"]');
    expect(affiliateRow?.querySelectorAll(".matrix-cell--muted")).toHaveLength(4);
  });

  it("tints cells by direction — green up, red down", () => {
    const { container } = render(<HomeOverview envelope={SAMPLE} />);
    const tones = Array.from(
      container.querySelectorAll('tr[data-channel="product_card"] .matrix-cell'),
      (td) => td.className,
    );
    const model = buildHomeOverview(SAMPLE).groups[0].rows[0];
    expect(tones).toEqual(model.cells.map((cell) => `matrix-cell matrix-cell--${cell.tone}`));
  });

  it("shows Chưa có dữ liệu for a stream the report does not carry", () => {
    const { container } = render(<HomeOverview envelope={withoutShopTab(SAMPLE)} />);
    expect(container.querySelector('tr[data-channel="shop_tab"]')).toHaveTextContent(
      "Chưa có dữ liệu",
    );
  });
});

describe("/ — anonymous and signed-in doors", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("after Dùng thử Demo, shows the sample Home and performs no network call", async () => {
    window.sessionStorage.setItem(ENTRY_MODE_STORAGE_KEY, "replay");
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    renderHome();

    expect(await screen.findByTestId("mock-data-notice")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Ma trận 5 luồng truy cập" })).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("a first anonymous visit still gets the two doors", async () => {
    renderHome();
    expect(await screen.findByRole("button", { name: "Dùng thử Demo" })).toBeInTheDocument();
  });

  it("a signed-in seller lands on their own shop's report, never the sample", async () => {
    window.sessionStorage.setItem(
      AUTH_SESSION_STORAGE_KEY,
      JSON.stringify({ accessToken: "token-1", tokenType: "bearer" }),
    );
    window.sessionStorage.setItem(
      ACTIVE_SHOP_STORAGE_KEY,
      JSON.stringify({ id: "shop-1", name: "Shop Thật" }),
    );
    const loadAnalysis = vi.fn().mockResolvedValue(SAMPLE);

    renderHome(loadAnalysis);

    expect(await screen.findByRole("region", { name: "Ma trận 5 luồng truy cập" })).toBeInTheDocument();
    expect(loadAnalysis).toHaveBeenCalledWith({ token: "token-1", shopId: "shop-1" });
    expect(screen.queryByTestId("mock-data-notice")).toBeNull();
    expect(screen.queryByRole("button", { name: "Dùng thử Demo" })).toBeNull();
  });

  it("a signed-in shop with no report yet gets an honest empty state", async () => {
    window.sessionStorage.setItem(
      AUTH_SESSION_STORAGE_KEY,
      JSON.stringify({ accessToken: "token-1", tokenType: "bearer" }),
    );
    window.sessionStorage.setItem(
      ACTIVE_SHOP_STORAGE_KEY,
      JSON.stringify({ id: "shop-1", name: "Shop Thật" }),
    );

    renderHome(vi.fn().mockResolvedValue(null));

    expect(await screen.findByText("Chưa có báo cáo")).toBeInTheDocument();
    expect(screen.queryByTestId("mock-data-notice")).toBeNull();
  });
});
