import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import HomePage from "../app/page";
import { AnalysisPageClient } from "../components/analysis-page-client";
import { DecisionsPageClient } from "../components/decisions-page-client";
import { DemoStateProvider } from "../components/demo-state";
import { HomeOverview } from "../components/home/home-overview";
import { CONNECT_SHOP_HREF } from "../lib/app-navigation";
import { resolveSelection, specOf, STREAM_SPECS, streamView, type QueryState } from "../lib/phan-tich/model";
import { sampleEnvelope, sampleReport } from "../lib/phan-tich/sample-data";
import { SAMPLE_SHOP } from "../lib/quyet-dinh/sample-data";
import { ACTIVE_SHOP_STORAGE_KEY } from "../lib/shop-session";
import { buildHomeOverview } from "../lib/shop-report/home-metrics";
import { ShopReportProvider } from "../lib/shop-report/shop-report-context";
import { AUTH_SESSION_STORAGE_KEY } from "../lib/supabase-auth";

/**
 * P13 (owner, 2026-10-10): a signed-in seller with no TikTok Shop connected
 * sees the sample (the same cosmetics shop on Trang chủ, Phân tích and
 * Quyết định) under "Bạn đang xem dữ liệu mẫu · Kết nối TikTok Shop ›",
 * with no request; Home's sample agrees with Phân tích's figure for figure.
 */

let searchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => searchParams,
}));

const REPORT = sampleReport();

function queryOf(href: string): QueryState {
  const p = new URLSearchParams(href.split("?")[1] ?? "");
  return { tab: p.get("tab"), stream: p.get("stream"), metric: p.get("metric"), huong: p.get("huong"), row: p.get("row") };
}

function signInWithoutShop() {
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "token-1", tokenType: "bearer" }));
}

function renderInShell(page: React.ReactNode, loadAnalysis = vi.fn()) {
  render(
    <DemoStateProvider>
      <ShopReportProvider loadAnalysis={loadAnalysis}>{page}</ShopReportProvider>
    </DemoStateProvider>,
  );
  return loadAnalysis;
}

async function expectStrip() {
  const strip = await screen.findByTestId("no-shop-sample-strip");
  expect(strip).toHaveTextContent("Bạn đang xem dữ liệu mẫu · Kết nối TikTok Shop ›");
  expect(within(strip).getByRole("link", { name: "Kết nối TikTok Shop ›" })).toHaveAttribute("href", CONNECT_SHOP_HREF);
  expect(CONNECT_SHOP_HREF).toBe("/auth/connect-shop");
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  searchParams = new URLSearchParams();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("signed in, no TikTok Shop → the sample under the connect strip", () => {
  it("Trang chủ: the sample Home, the strip, no report read and no request", async () => {
    signInWithoutShop();
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const loadAnalysis = renderInShell(<HomePage />);

    await expectStrip();
    expect(screen.getByTestId("mock-data-notice")).toHaveTextContent(SAMPLE_SHOP.name);
    expect(screen.getByRole("region", { name: "Ma trận 5 luồng truy cập" })).toBeInTheDocument();
    expect(screen.queryByText(/Bạn chưa chọn shop/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Dùng thử Demo" })).toBeNull();
    expect(loadAnalysis).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("Phân tích: the sample report and rankings, the strip, no request", async () => {
    signInWithoutShop();
    searchParams = new URLSearchParams("tab=san-pham&stream=the-san-pham&metric=ctor");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const loadAnalysis = renderInShell(<AnalysisPageClient />);

    await expectStrip();
    expect(await screen.findByTestId("ranking-table")).toBeInTheDocument();
    expect(screen.getByTestId("mock-data-notice")).toHaveTextContent(SAMPLE_SHOP.name);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/^Thẻ sản phẩm: CTOR giảm/);
    expect(screen.queryByText(/Bạn chưa chọn shop/)).toBeNull();
    expect(loadAnalysis).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("Quyết định: the sample cards, the strip, no request", async () => {
    signInWithoutShop();
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    renderInShell(<DecisionsPageClient />);

    await expectStrip();
    expect(await screen.findByTestId("mock-data-notice")).toHaveTextContent(SAMPLE_SHOP.name);
    expect(document.querySelector('[data-decision-id="sample-sm-012"]')).not.toBeNull();
    expect(screen.queryByText(/Bạn chưa chọn shop/)).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("signed in WITH a shop: the shop's own report, no strip, no sample", async () => {
    signInWithoutShop();
    window.localStorage.setItem(ACTIVE_SHOP_STORAGE_KEY, JSON.stringify({ id: "shop-1", name: "Shop Thật" }));
    const loadAnalysis = renderInShell(<HomePage />, vi.fn().mockResolvedValue(sampleEnvelope()));

    expect(await screen.findByRole("region", { name: "Ma trận 5 luồng truy cập" })).toBeInTheDocument();
    expect(loadAnalysis).toHaveBeenCalledWith({ token: "token-1", shopId: "shop-1" });
    expect(screen.queryByTestId("no-shop-sample-strip")).toBeNull();
    expect(screen.queryByTestId("mock-data-notice")).toBeNull();
  });

  it("anonymous visitors get no strip (it is only for a signed-in seller)", async () => {
    renderInShell(<AnalysisPageClient />);
    expect(await screen.findByTestId("mock-data-notice")).toBeInTheDocument();
    expect(screen.queryByTestId("no-shop-sample-strip")).toBeNull();
  });
});

describe("Trang chủ's sample = Phân tích's sample (P13)", () => {
  const home = buildHomeOverview(sampleEnvelope());

  it("one shop name on all three pages", () => {
    expect(home.shopName).toBe(SAMPLE_SHOP.name);
    expect(REPORT.shop_name).toBe(SAMPLE_SHOP.name);
  });

  it("every stream Phân tích shows has the same last-window figures on Home", () => {
    for (const spec of STREAM_SPECS) {
      const row = home.groups.flatMap((g) => g.rows).find((r) => r.channel === spec.stream);
      expect(row?.missing).toBe(false);
      const cells = streamView(REPORT, spec.stream).cells.filter((c) => c.metric !== "gmv");
      for (const cell of cells) {
        const homeCell = row?.cells.find((c) => c.metric === cell.metric);
        const channel = REPORT.channels.find((c) => c.channel === spec.stream);
        expect(homeCell?.last, `${spec.stream} ${cell.metric}`).toBeCloseTo(
          cell.metric === "impressions"
            ? (channel?.comparison.last.impressions as number)
            : (channel?.comparison.factors?.find((f) => f.factor === cell.metric)?.last as number),
          6,
        );
      }
    }
  });

  it("the CTOR cell of Thẻ sản phẩm reads the same on Home and in Phân tích", () => {
    const { container } = render(<HomeOverview envelope={sampleEnvelope()} sample />);
    const link = within(container).getByRole("link", { name: /^CTOR Thẻ sản phẩm:/ });
    const phanTich = streamView(REPORT, "product_card").cells.find((c) => c.metric === "ctor");
    expect(phanTich?.value).toBe("5,14 %");
    expect(link).toHaveTextContent("5,14 %");
    expect(link).toHaveAttribute("href", "/analytics?tab=san-pham&stream=the-san-pham&metric=ctor");
  });

  it("Home's links land on a real Phân tích stream, and on the same cell where it is clickable", () => {
    const linked = home.groups.flatMap((g) => g.rows).flatMap((r) => r.cells.map((c) => ({ row: r, cell: c })));
    const hrefs = linked.filter(({ cell }) => cell.href);
    expect(hrefs.length).toBe(16);
    for (const { row, cell } of hrefs) {
      const selection = resolveSelection(REPORT, queryOf(cell.href as string));
      expect(selection.stream).toBe(row.channel);
      if (specOf(row.channel as never).clickable.includes(cell.metric)) {
        expect(selection.metric).toBe(cell.metric);
      } else {
        // Content streams' CTOR / AOV are grey in Phân tích: the link opens the stream's weakest cell.
        expect(selection.metric).not.toBeNull();
      }
    }
  });

  it("Liên kết is in the sample, greyed and unlinked; the cards sum the additive streams", () => {
    const affiliate = home.groups[2].rows[0];
    expect(affiliate.missing).toBe(false);
    expect(affiliate.cells.every((c) => c.href === null)).toBe(true);
    const additive = REPORT.channels.filter((c) => c.additive);
    expect(additive.map((c) => c.channel)).toEqual(["product_card", "seller_video", "seller_live", "affiliate"]);
    const gmv = additive.reduce((sum, c) => sum + c.comparison.last.gmv, 0);
    expect(home.cards[0].last).toBeCloseTo(gmv * 30);
  });
});

describe("Phân tích header alignment (P13 bug)", () => {
  it("the page header's column is left-aligned, not the shared header's flex-end", () => {
    const css = readFileSync(resolve(__dirname, "../app/phan-tich.css"), "utf8");
    const rule = css.match(/\.pa-head,\s*\.pa-page > \.page-header \{([^}]*)\}/);
    expect(rule?.[1]).toMatch(/flex-direction:\s*column/);
    expect(rule?.[1]).toMatch(/align-items:\s*flex-start/);
  });
});
