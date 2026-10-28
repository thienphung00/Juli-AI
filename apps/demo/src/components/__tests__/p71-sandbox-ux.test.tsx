import type { DemoDecisionItem } from "@juli/contracts";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { decisionCardHref, indexCards, SHOP_DECISIONS_HREF } from "../../lib/phan-tich/cards";
import { sampleEnvelope, sampleReport } from "../../lib/phan-tich/sample-data";
import { SANDBOX_NO_AFFILIATE, SANDBOX_NO_CONTENT, isSandboxReport } from "../../lib/shop-analysis/derive";
import type { ShopAnalysisEnvelope, ShopDiagnosisReport } from "../../lib/shop-analysis/types";
import { StreamMatrix } from "../home/home-overview";
import { PhanTichView } from "../phan-tich/phan-tich-view";

/**
 * P71: on the reviewer's TikTok sandbox shop (no traffic, no videos, no creators),
 * Phân tích links to the shop's open cards, and Trang chủ / Phân tích › Nội dung say in
 * one line why Video / LIVE / Liên kết are empty. Real shops are unchanged.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/analytics",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(cleanup);

const BN500 = "1738221500563949187";

/** The sandbox report: orders-sourced, product streams without a diagnosis, no content / affiliate rows. */
function sandboxReport(): ShopDiagnosisReport {
  const report = sampleReport();
  return {
    ...report,
    metrics_source: "orders",
    channels: report.channels
      .filter((row) => row.channel === "product_card" || row.channel === "shop_tab")
      .map((row) => ({ ...row, comparison: { ...row.comparison, factors: [] } })),
  };
}

function item(id: string, title: string, productId: string | null): DemoDecisionItem {
  return {
    id,
    title,
    description: "",
    severity: "medium",
    priority: 0,
    computed_at: null,
    surfaced_at: null,
    is_executable: true,
    recommendation: {
      source_kpi_ids: [],
      diagnosis: {
        stage: { code: "promotion", label: "Khuyến mãi" },
        main_kpi: { key: "promotion", label: "Khuyến mãi", value: "+1" },
        ...(productId ? { tiktok_product_id: productId } : {}),
      },
      card: { product_title: title },
    },
  } as unknown as DemoDecisionItem;
}

const CARDS = [
  item("c-promo", "Tạo khuyến mãi giảm giá cho Bình Nước Thép Không Gỉ 500ml", BN500),
  item("c-create", "Tạo sản phẩm mới từ Áo thun", "1738000000000000001"),
];

function renderView(report: ShopDiagnosisReport, tab: string, cards: readonly DemoDecisionItem[] = CARDS) {
  return render(
    <PhanTichView
      loadDecisions={() => Promise.resolve(cards)}
      loadRanking={() => Promise.resolve(null)}
      query={{ tab }}
      report={report}
    />,
  );
}

describe("P71 Phân tích → Quyết định", () => {
  it("indexes every open card, metric or not", () => {
    const index = indexCards(CARDS);
    expect(index.total).toBe(2);
    expect(index.anyCardId(BN500)).toBe("c-promo");
    expect(index.anyCardId("nope")).toBeNull();
    expect(index.find(BN500, "ctr")).toBeNull(); // a promotion card is about no metric
  });

  it("links the sandbox's Sản phẩm to the shop's cards", async () => {
    renderView(sandboxReport(), "san-pham");
    const block = await screen.findByTestId("pa-shop-cards");
    expect(block).toHaveTextContent("Có 2 đề xuất cho shop");
    const links = within(block).getAllByRole("link", { name: "Xem đề xuất ›" });
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      SHOP_DECISIONS_HREF,
      decisionCardHref("c-promo"),
      decisionCardHref("c-create"),
    ]);
    expect(block).toHaveTextContent("Tạo khuyến mãi giảm giá cho Bình Nước Thép Không Gỉ 500ml");
  });

  it("shows no block when the shop has no open card", async () => {
    renderView(sandboxReport(), "san-pham", []);
    await Promise.resolve();
    expect(screen.queryByTestId("pa-shop-cards")).toBeNull();
  });
});

describe("P71 honest empty state on the sandbox", () => {
  it("knows a sandbox report by its metrics_source", () => {
    expect(isSandboxReport(sandboxReport())).toBe(true);
    expect(isSandboxReport(sampleReport())).toBe(false);
  });

  it("Phân tích › Nội dung is one line, no empty streams", () => {
    renderView(sandboxReport(), "noi-dung", []);
    expect(screen.getByTestId("pa-sandbox-no-content")).toHaveTextContent(SANDBOX_NO_CONTENT);
    expect(screen.queryAllByTestId("pa-stream")).toHaveLength(0);
  });

  it("a real shop's Nội dung keeps its streams", () => {
    renderView(sampleReport(), "noi-dung", []);
    expect(screen.queryByTestId("pa-sandbox-no-content")).toBeNull();
    expect(screen.getAllByTestId("pa-stream").length).toBeGreaterThan(0);
  });

  it("Trang chủ's matrix says why Video / LIVE and Liên kết are empty", () => {
    const envelope: ShopAnalysisEnvelope = { ...sampleEnvelope(), report: sandboxReport() };
    render(<StreamMatrix envelope={envelope} />);
    expect(screen.getByTestId("sandbox-empty-content")).toHaveTextContent(SANDBOX_NO_CONTENT);
    expect(screen.getByTestId("sandbox-empty-affiliate")).toHaveTextContent(SANDBOX_NO_AFFILIATE);
    expect(document.querySelector('[data-channel="seller_video"]')).toBeNull();
    expect(document.querySelector('[data-channel="product_card"]')).not.toBeNull();
    expect(screen.queryByText("Chưa có dữ liệu")).toBeNull();
  });

  it("a real shop's matrix keeps its rows, even an empty one", () => {
    const report = sampleReport();
    const envelope: ShopAnalysisEnvelope = {
      ...sampleEnvelope(),
      report: { ...report, channels: report.channels.filter((row) => row.channel !== "affiliate") },
    };
    render(<StreamMatrix envelope={envelope} />);
    expect(screen.queryByTestId("sandbox-empty-affiliate")).toBeNull();
    expect(document.querySelector('[data-channel="affiliate"]')).toHaveTextContent("Chưa có dữ liệu");
  });
});
