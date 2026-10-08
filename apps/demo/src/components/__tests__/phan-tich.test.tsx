import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AnalysisPageClient } from "../analysis-page-client";
import { PhanTichView } from "../phan-tich/phan-tich-view";
import { closingRows } from "../phan-tich/ranking-table";
import { loadSampleRanking } from "../phan-tich/sample-phan-tich";
import { SignedInPhanTich } from "../phan-tich/signed-in-phan-tich";
import {
  findBottleneck,
  pageTitle,
  resolveSelection,
  suggestionLine,
} from "../../lib/phan-tich/model";
import { DEMO_RANKINGS_API_PATH, fetchMetricRanking } from "../../lib/phan-tich/rankings-client";
import type { RankingEnvelope, RankingLoader } from "../../lib/phan-tich/types";
import sampleEnvelope from "../../lib/shop-analysis/sample-report.json";
import sampleRankings from "../../lib/shop-analysis/sample-rankings.json";
import type { ShopAnalysisEnvelope } from "../../lib/shop-analysis/types";
import { ACTIVE_SHOP_STORAGE_KEY } from "../../lib/shop-session";
import { ShopReportProvider } from "../../lib/shop-report/shop-report-context";
import { AUTH_SESSION_STORAGE_KEY } from "../../lib/supabase-auth";
import { signedMoney } from "../../lib/vn-format";

/**
 * Phân tích (AC-8.6, ADR-109 decisions 2–5): sub-tabs and URL state, the
 * clickable cells, the bottleneck, the ranking table and its closing rows,
 * the "Ví dụ" panel, the hero list and the collapsed sections.
 */

const searchParams = new URLSearchParams();
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  usePathname: () => "/analytics",
  useRouter: () => ({ push: vi.fn(), replace }),
  useSearchParams: () => searchParams,
}));

const SAMPLE = sampleEnvelope as unknown as ShopAnalysisEnvelope;
const RANKINGS = sampleRankings as unknown as Record<string, Record<string, RankingEnvelope>>;
const CTOR = RANKINGS.product_card.ctor;

function renderView(query: Record<string, string> = {}, loadRanking: RankingLoader = loadSampleRanking) {
  const onNavigate = vi.fn();
  const utils = render(
    <PhanTichView envelope={SAMPLE} loadRanking={loadRanking} onNavigate={onNavigate} query={query} sample />,
  );
  return { ...utils, onNavigate };
}

function cell(name: RegExp) {
  return screen.getByRole("button", { name });
}

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
  replace.mockReset();
  for (const key of [...searchParams.keys()]) searchParams.delete(key);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Phân tích model", () => {
  it("picks the Rõ factor with the largest negative GMV contribution as the bottleneck", () => {
    const bottleneck = findBottleneck(SAMPLE.report, "san-pham");
    expect(bottleneck).toMatchObject({ stream: "product_card", metric: "ctor" });
    // AOV on Thẻ sản phẩm is also Rõ and negative, but smaller; Tab cửa hàng is Tham khảo only.
    const card = SAMPLE.report.channels.find((c) => c.channel === "product_card");
    const ctor = card?.comparison.factors.find((f) => f.factor === "ctor");
    expect(bottleneck?.contribution).toBe(ctor?.contribution);
    // Nội dung: nothing negative is Rõ in the sample → no bottleneck.
    expect(findBottleneck(SAMPLE.report, "noi-dung")).toBeNull();
  });

  it("builds a conclusion-style title from the data", () => {
    expect(pageTitle(SAMPLE.report, "san-pham")).toBe("Thẻ sản phẩm: CTOR giảm 15,2 %");
    expect(pageTitle(SAMPLE.report, "noi-dung")).toBe("Nội dung: không có chỉ số nào kéo GMV xuống rõ rệt");
  });

  it("writes the Juli gợi ý line from the report only, with no invented target", () => {
    const bottleneck = findBottleneck(SAMPLE.report, "san-pham");
    const line = suggestionLine(SAMPLE.report, bottleneck!);
    expect(line).toMatch(/^Tối ưu CTOR: khách thêm giỏ rồi bỏ: Đơn\/thêm giỏ .* → .* · kéo GMV\/ngày −/);
    expect(line).not.toMatch(/Mục tiêu/);
  });

  it("resolves Home links, and falls back to the bottleneck for a cell that is not clickable", () => {
    expect(resolveSelection(SAMPLE.report, { tab: "noi-dung", stream: "live", metric: "ctr" })).toEqual({
      tab: "noi-dung",
      cell: { stream: "seller_live", metric: "ctr" },
    });
    // The stream decides the tab even when `tab` disagrees.
    expect(resolveSelection(SAMPLE.report, { tab: "noi-dung", stream: "tab-cua-hang", metric: "aov" }).cell).toEqual({
      stream: "shop_tab",
      metric: "aov",
    });
    // Video AOV is shown, not clickable (d.4) → the sub-tab's default.
    expect(resolveSelection(SAMPLE.report, { stream: "video", metric: "aov" })).toEqual({
      tab: "noi-dung",
      cell: { stream: "seller_video", metric: "impressions" },
    });
    expect(resolveSelection(SAMPLE.report, {}).cell).toEqual({ stream: "product_card", metric: "ctor" });
  });
});

describe("Phân tích view", () => {
  it("opens on Sản phẩm with the bottleneck selected, outlined and explained", async () => {
    renderView();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Thẻ sản phẩm: CTOR giảm 15,2 %");
    expect(screen.getByText(/Phân tích · Sản phẩm/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Sản phẩm" })).toHaveAttribute("aria-selected", "true");

    const ctor = cell(/^CTOR · Thẻ sản phẩm/);
    expect(ctor).toHaveAttribute("aria-pressed", "true");
    expect(ctor).toHaveClass("pt-tile--bottleneck");
    expect(screen.getByTestId("juli-suggestion")).toHaveTextContent(/Juli gợi ý:.*Tối ưu CTOR/);
    expect(screen.getByTestId("juli-suggestion")).not.toHaveTextContent("Mục tiêu");
    expect(await screen.findByRole("heading", { name: "SKU kéo CTOR xuống" })).toBeInTheDocument();
  });

  it("switches sub-tab and writes it into the URL", async () => {
    const user = userEvent.setup();
    const { onNavigate } = renderView();
    await user.click(screen.getByRole("tab", { name: "Nội dung" }));

    expect(onNavigate).toHaveBeenLastCalledWith("/analytics?tab=noi-dung");
    expect(screen.getByRole("tab", { name: "Nội dung" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "Video của shop" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "LIVE của shop" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Thẻ sản phẩm" })).toBeNull();
    expect(screen.queryByTestId("juli-suggestion")).toBeNull();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/^Nội dung:/);
  });

  it("lands on a Home link's stream × metric", async () => {
    const loadRanking = vi.fn(loadSampleRanking);
    renderView({ tab: "san-pham", stream: "tab-cua-hang", metric: "aov" }, loadRanking);
    expect(cell(/^AOV · Tab cửa hàng/)).toHaveAttribute("aria-pressed", "true");
    expect(loadRanking).toHaveBeenCalledWith("shop_tab", "aov");
    expect(await screen.findByRole("heading", { name: "SKU kéo AOV xuống" })).toBeInTheDocument();
  });

  it("a clicked cell re-ranks the table: fetch with its stream × metric, URL updated", async () => {
    const user = userEvent.setup();
    const loadRanking = vi.fn(loadSampleRanking);
    const { onNavigate } = renderView({}, loadRanking);
    await screen.findByRole("heading", { name: "SKU kéo CTOR xuống" });

    await user.click(cell(/^AOV · Thẻ sản phẩm/));
    expect(loadRanking).toHaveBeenLastCalledWith("product_card", "aov");
    expect(onNavigate).toHaveBeenLastCalledWith("/analytics?tab=san-pham&stream=the-san-pham&metric=aov");
    expect(cell(/^AOV · Thẻ sản phẩm/)).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByRole("heading", { name: "SKU kéo AOV xuống" })).toBeInTheDocument();

    // The CTOR tile carries its two steps, each clickable on Thẻ sản phẩm.
    await user.click(cell(/^Đơn\/thêm giỏ · Thẻ sản phẩm/));
    expect(loadRanking).toHaveBeenLastCalledWith("product_card", "orders_per_cart");
    expect(await screen.findByRole("heading", { name: "SKU kéo Đơn/thêm giỏ xuống" })).toBeInTheDocument();

    // Back to a cell already loaded: no second request.
    const calls = loadRanking.mock.calls.length;
    await user.click(cell(/^AOV · Thẻ sản phẩm/));
    expect(loadRanking.mock.calls.length).toBe(calls);
  });

  it("content streams: Video CTOR/AOV and LIVE AOV are shown, not clickable", async () => {
    renderView({ tab: "noi-dung" });
    const video = screen.getByRole("article", { name: "Video của shop" });
    const live = screen.getByRole("article", { name: "LIVE của shop" });

    expect(within(video).getAllByRole("button").map((b) => b.getAttribute("data-metric"))).toEqual(["impressions", "ctr"]);
    expect(within(live).getAllByRole("button").map((b) => b.getAttribute("data-metric"))).toEqual([
      "impressions",
      "ctr",
      "ctor",
    ]);
    expect(within(video).getAllByText("phụ thuộc sản phẩm → xem tab Sản phẩm")).toHaveLength(2);
    expect(within(live).getAllByText("phụ thuộc sản phẩm → xem tab Sản phẩm")).toHaveLength(1);
    // The default cell of a sub-tab without a bottleneck ranks videos.
    expect(await screen.findByRole("heading", { name: "Video kéo Lượt hiển thị sản phẩm xuống" })).toBeInTheDocument();
  });

  it("lists rows with metric prior → last, GMV/ngày and confidence; closing rows add up to Tổng", async () => {
    const user = userEvent.setup();
    renderView();
    const table = await screen.findByTestId("ranking-table");
    const payload = CTOR.ranking;

    const listed = within(table).getAllByRole("row").filter((r) => r.hasAttribute("data-row-id"));
    expect(listed.map((r) => r.getAttribute("data-row-id"))).toEqual(payload.down.map((r) => r.id));
    expect(listed[0]).toHaveTextContent("s1");
    expect(listed[0]).toHaveTextContent("Bình giữ nhiệt inox 500ml");
    expect(listed[0]).toHaveTextContent(/6,28 % → 3,67 %/);
    expect(listed[0]).toHaveTextContent(signedMoney(payload.down[0].gmv_per_day));
    expect(within(listed[0]).getByText("Rõ")).toBeInTheDocument();

    expect(within(table).getByText("Thay đổi cơ cấu sản phẩm")).toBeInTheDocument();
    expect(within(table).getByTestId("ranking-total")).toHaveTextContent(`Tổng = ${signedMoney(payload.stream_factor_gmv)}`);

    for (const direction of ["down", "up"] as const) {
      const shown = (direction === "down" ? payload.down : payload.up).reduce((s, r) => s + r.gmv_per_day, 0);
      const closing = closingRows(payload, direction).reduce((s, r) => s + r.gmv, 0);
      expect(shown + closing).toBeCloseTo(payload.stream_factor_gmv, 0);
    }

    await user.click(screen.getByRole("button", { name: "Kéo lên" }));
    expect(screen.getByRole("heading", { name: "SKU kéo CTOR lên" })).toBeInTheDocument();
    const upRows = within(screen.getByTestId("ranking-table"))
      .getAllByRole("row")
      .filter((r) => r.hasAttribute("data-row-id"));
    expect(upRows.map((r) => r.getAttribute("data-row-id"))).toEqual(payload.up.map((r) => r.id));
    expect(screen.getByText(`${payload.down.length} sản phẩm kéo xuống (xem Kéo xuống)`)).toBeInTheDocument();
  });

  it("LIVE rows read title · dd/mm/yyyy", async () => {
    renderView({ stream: "live", metric: "ctr" });
    const table = await screen.findByTestId("ranking-table");
    expect(screen.getByRole("heading", { name: "Phiên LIVE kéo CTR xuống" })).toBeInTheDocument();
    const first = RANKINGS.seller_live.ctr.ranking.down[0];
    expect(within(table).getByText(first.name)).toBeInTheDocument();
    expect(first.name).toMatch(/ · \d{2}\/\d{2}\/\d{4}$/);
  });

  it("404 → 'Chưa có bảng xếp hạng cho chỉ số này'; a failure offers Thử lại", async () => {
    const user = userEvent.setup();
    renderView({}, vi.fn().mockResolvedValue(null));
    expect(await screen.findByText("Chưa có bảng xếp hạng cho chỉ số này")).toBeInTheDocument();
    expect(screen.queryByTestId("ranking-table")).toBeNull();
    expect(screen.queryByTestId("detail-panel")).toBeNull();

    const failing = vi.fn().mockRejectedValueOnce(new Error("500")).mockImplementation(loadSampleRanking);
    renderView({ stream: "the-san-pham", metric: "ctr" }, failing);
    expect(await screen.findByText("Không tải được bảng xếp hạng. Vui lòng thử lại.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(await screen.findByRole("heading", { name: "SKU kéo CTR xuống" })).toBeInTheDocument();
    expect(failing).toHaveBeenCalledTimes(2);
  });

  it("a clicked row opens the Ví dụ panel: hero profile when present, else its row numbers", async () => {
    const user = userEvent.setup();
    renderView();
    const panel = await screen.findByTestId("detail-panel");
    // Default: the first row (s1, a hero) with its 5-channel profile.
    expect(panel).toHaveTextContent("Ví dụ · s1");
    expect(within(panel).getByRole("region", { name: /Hồ sơ 5 kênh/ })).toBeInTheDocument();
    expect(within(panel).getByText("Thẻ sản phẩm của người bán")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Thớt gỗ tròn 30cm/ }));
    const next = screen.getByTestId("detail-panel");
    expect(next).toHaveTextContent("Ví dụ · s7");
    expect(next).toHaveTextContent("Thớt gỗ tròn 30cm");
    expect(within(next).queryByRole("region", { name: /Hồ sơ 5 kênh/ })).toBeNull();
    expect(next).toHaveTextContent(/không thuộc năm sản phẩm chủ lực/);
    expect(screen.getByRole("button", { name: /Thớt gỗ tròn 30cm/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("hero products expand in place; Khuyến mãi, Dòng thời gian and Cách tính start collapsed", async () => {
    const user = userEvent.setup();
    renderView();
    await screen.findByTestId("ranking-table");

    const hero = screen.getByRole("button", { name: /Hộp cơm giữ nhiệt 3 tầng/ });
    expect(hero).toHaveAttribute("aria-expanded", "false");
    await user.click(hero);
    expect(hero).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("region", { name: "Chỉ số của Hộp cơm giữ nhiệt 3 tầng" })).toBeInTheDocument();

    for (const id of ["khuyen-mai", "dong-thoi-gian", "cach-tinh"]) {
      const section = screen.getByTestId(`more-${id}`);
      const toggle = within(section).getByRole("button", { name: "Xem thêm" });
      expect(toggle).toHaveAttribute("aria-expanded", "false");
      expect(document.getElementById(`${id}-body`)).toBeEmptyDOMElement();
    }
    const promos = screen.getByTestId("more-khuyen-mai");
    await user.click(within(promos).getByRole("button", { name: "Xem thêm" }));
    expect(within(promos).getByRole("button", { name: "Thu gọn" })).toHaveAttribute("aria-expanded", "true");
    expect(document.getElementById("khuyen-mai-body")).not.toBeEmptyDOMElement();
  });

  it("a stream without data says so and has no cells", () => {
    const envelope = structuredClone(SAMPLE);
    envelope.report.channels = envelope.report.channels.filter((c) => c.channel !== "shop_tab");
    render(<PhanTichView envelope={envelope} loadRanking={loadSampleRanking} query={{}} />);
    const tab = screen.getByRole("article", { name: "Tab cửa hàng" });
    expect(tab).toHaveTextContent("Chưa có dữ liệu");
    expect(within(tab).queryAllByRole("button")).toHaveLength(0);
  });
});

describe("Phân tích — signed in", () => {
  it("reads each clicked cell's ranking with the token and the acting shop", async () => {
    const fetchRanking = vi.fn().mockResolvedValue(CTOR);
    render(<SignedInPhanTich envelope={SAMPLE} fetchRanking={fetchRanking} query={{}} shopId="shop-1" token="token-1" />);
    expect(await screen.findByTestId("ranking-table")).toBeInTheDocument();
    expect(fetchRanking).toHaveBeenCalledWith({ token: "token-1", shopId: "shop-1", stream: "product_card", metric: "ctor" });
    expect(screen.queryByTestId("mock-data-notice")).toBeNull();
  });

  it("the rankings client sends bearer + X-Shop-Id, and maps 404 to null", async () => {
    const ok = vi.fn().mockResolvedValue(new Response(JSON.stringify(CTOR), { status: 200 }));
    await expect(
      fetchMetricRanking({ token: "t", shopId: "s", stream: "seller_live", metric: "ctor", fetchImpl: ok }),
    ).resolves.toEqual(CTOR);
    const [url, init] = ok.mock.calls[0];
    expect(url).toBe(`${DEMO_RANKINGS_API_PATH}?stream=seller_live&metric=ctor`);
    expect(init.headers).toMatchObject({ Authorization: "Bearer t", "X-Shop-Id": "s" });

    const missing = vi.fn().mockResolvedValue(new Response("{}", { status: 404 }));
    await expect(
      fetchMetricRanking({ token: "t", shopId: "s", stream: "product_card", metric: "aov", fetchImpl: missing }),
    ).resolves.toBeNull();
    const broken = vi.fn().mockResolvedValue(new Response("{}", { status: 500 }));
    await expect(
      fetchMetricRanking({ token: "t", shopId: "s", stream: "product_card", metric: "aov", fetchImpl: broken }),
    ).rejects.toThrow();
  });

  it("/analytics reads the report once, through the shell's useShopReport", async () => {
    window.sessionStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "token-1", tokenType: "bearer" }));
    window.sessionStorage.setItem(ACTIVE_SHOP_STORAGE_KEY, JSON.stringify({ id: "shop-1", name: "Shop Thật" }));
    searchParams.set("tab", "noi-dung");
    const loadAnalysis = vi.fn().mockResolvedValue(SAMPLE);
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 404 }));

    render(
      <ShopReportProvider loadAnalysis={loadAnalysis}>
        <AnalysisPageClient />
      </ShopReportProvider>,
    );

    expect(await screen.findByRole("tab", { name: "Nội dung" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("Chưa có bảng xếp hạng cho chỉ số này")).toBeInTheDocument();
    expect(loadAnalysis).toHaveBeenCalledTimes(1);
    const urls = fetchSpy.mock.calls.map(([u]) => String(u));
    expect(urls.some((u) => u.startsWith("/v1/demo/analysis?") || u === "/v1/demo/analysis")).toBe(false);
    expect(urls).toEqual([`${DEMO_RANKINGS_API_PATH}?stream=seller_video&metric=impressions`]);
  });

  it("a signed-in shop with no report gets an honest empty state, never the sample", async () => {
    window.sessionStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "token-1", tokenType: "bearer" }));
    window.sessionStorage.setItem(ACTIVE_SHOP_STORAGE_KEY, JSON.stringify({ id: "shop-1", name: "Shop Thật" }));
    render(
      <ShopReportProvider loadAnalysis={vi.fn().mockResolvedValue(null)}>
        <AnalysisPageClient />
      </ShopReportProvider>,
    );
    expect(await screen.findByText("Chưa có báo cáo")).toBeInTheDocument();
    expect(screen.queryByTestId("mock-data-notice")).toBeNull();
  });

  it("an anonymous visitor gets the sample and issues no request", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(
      <ShopReportProvider>
        <AnalysisPageClient />
      </ShopReportProvider>,
    );
    expect(await screen.findByTestId("mock-data-notice")).toBeInTheDocument();
    expect(await screen.findByTestId("ranking-table")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
