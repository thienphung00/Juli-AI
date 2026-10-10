import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AnalysisPageClient } from "../analysis-page-client";
import { PhanTichView } from "../phan-tich/phan-tich-view";
import { loadSampleDecisions, loadSampleRanking } from "../phan-tich/sample-phan-tich";
import { SignedInPhanTich } from "../phan-tich/signed-in-phan-tich";
import { SampleQuyetDinh } from "../quyet-dinh/sample-quyet-dinh";
import { analysisHrefForDecision, decisionCardHref, indexCards } from "../../lib/phan-tich/cards";
import { calendarView, promoView } from "../../lib/phan-tich/extras";
import { deltaChip, kMoney, signedKMoney } from "../../lib/phan-tich/format";
import { analysisHref, defaultStream, pageTitle, resolveSelection, streamView, streamsOf, type QueryState } from "../../lib/phan-tich/model";
import { DEMO_RANKINGS_API_PATH, fetchMetricRanking } from "../../lib/phan-tich/rankings-client";
import { sampleEnvelope, sampleProductId, sampleRankings, sampleReport } from "../../lib/phan-tich/sample-data";
import type { RankingEnvelope } from "../../lib/phan-tich/types";
import { createSampleQdClients } from "../../lib/quyet-dinh/sample-clients";
import { SAMPLE_CARDS, sampleDecision } from "../../lib/quyet-dinh/sample-data";
import { ACTIVE_SHOP_STORAGE_KEY } from "../../lib/shop-session";
import { ShopReportProvider } from "../../lib/shop-report/shop-report-context";
import { AUTH_SESSION_STORAGE_KEY } from "../../lib/supabase-auth";
import { resolveTab } from "../../lib/quyet-dinh/copy";
import type { QdQuery } from "../quyet-dinh/quyet-dinh-view";

/**
 * Phân tích (ADR-109 Amendment 2, AC-12.x): collapsible streams, cells with
 * ₫/day impact, re-ranking, rows that expand in place, "Còn lại" / "Tổng",
 * the two-way links with Đề xuất, both doors.
 */

const searchParams = new URLSearchParams();
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  usePathname: () => "/analytics",
  useRouter: () => ({ push: vi.fn(), replace }),
  useSearchParams: () => searchParams,
}));

const REPORT = sampleReport();
const RANKINGS = sampleRankings();
const CTOR = RANKINGS.product_card!.ctor as RankingEnvelope;
const SM012 = sampleProductId("SM-012");

function queryOf(href: string): QueryState {
  const p = new URLSearchParams(href.split("?")[1] ?? "");
  return { tab: p.get("tab"), stream: p.get("stream"), metric: p.get("metric"), huong: p.get("huong"), row: p.get("row") };
}

/** The view with its URL state held locally, as the page does through the router. */
function Harness({ initial, spy }: { initial: string; spy?: (href: string) => void }) {
  const [href, setHref] = useState(initial);
  return (
    <PhanTichView
      loadDecisions={loadSampleDecisions}
      loadRanking={loadSampleRanking}
      onNavigate={(next) => {
        spy?.(next);
        setHref(next);
      }}
      query={queryOf(href)}
      report={REPORT}
      sample
    />
  );
}

function renderView(initial = "/analytics") {
  const spy = vi.fn();
  const utils = render(<Harness initial={initial} spy={spy} />);
  return { ...utils, spy };
}

const stream = (name: string) => screen.getAllByTestId("pa-stream").find((s) => within(s).queryByRole("heading", { level: 2, name }))!;
const rowOf = (text: string) => screen.getAllByTestId("pa-row").find((r) => r.textContent?.includes(text))!;

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
  it("formats like the artboards", () => {
    expect(kMoney(3_619_000)).toBe("3,6 tr ₫");
    expect(signedKMoney(-250_000)).toBe("−250k ₫");
    expect(signedKMoney(620_000)).toBe("+620k ₫");
    expect(signedKMoney(300)).toBe("0k ₫");
    expect(deltaChip(100, 107.6)).toEqual({ text: "▲ 7,6 %", tone: "up" });
    expect(deltaChip(100, 84.8)).toEqual({ text: "▼ 15,2 %", tone: "down" });
  });

  it("each cell carries the report's ₫/day contribution; the weakest gets ✦ Juli gợi ý", () => {
    const card = streamView(REPORT, "product_card");
    expect(card.cells.map((c) => c.label)).toEqual(["Hiển thị/ngày", "CTR", "CTOR", "AOV", "GMV/ngày"]);
    expect(card.cells.map((c) => c.impact)).toEqual(["+620k ₫/ngày", "−12k ₫/ngày", "−250k ₫/ngày", "−105k ₫/ngày", "Tổng của 4 ô"]);
    expect(card.cells.find((c) => c.weak)?.metric).toBe("ctor");
    expect(card.weakText).toBe("Yếu nhất: CTOR −250k ₫/ngày");
    expect(card.cells.map((c) => c.value).slice(0, 4)).toEqual(["9.913", "4,44 %", "5,14 %", "160k ₫"]);
    expect(card.gmvText).toBe("3,6 tr ₫/ngày");
    expect(card.cells[4].clickable).toBe(false);
    expect(streamView(REPORT, "shop_tab").weakText).toBe("Yếu nhất: AOV −31k ₫/ngày");
  });

  it("content streams grey the cells that depend on the product page", () => {
    const video = streamView(REPORT, "seller_video");
    expect(video.cells.filter((c) => c.grey && c.metric !== "gmv").map((c) => [c.metric, c.impact])).toEqual([
      ["ctor", "Phụ thuộc sản phẩm"],
      ["aov", "Phụ thuộc sản phẩm"],
    ]);
    expect(video.weakMetric).toBe("ctr");
    expect(streamView(REPORT, "seller_live").cells.filter((c) => c.grey).map((c) => c.metric)).toEqual(["aov", "gmv"]);
  });

  it("opens the stream whose weakest metric loses the most GMV; the h1 names it", () => {
    expect(defaultStream(streamsOf("san-pham").map((s) => streamView(REPORT, s.stream)))).toBe("product_card");
    expect(pageTitle(REPORT, "san-pham")).toMatch(/^Thẻ sản phẩm: CTOR giảm \d+ %$/);
    expect(pageTitle(REPORT, "noi-dung")).toMatch(/^Video: CTR giảm \d+ %$/);
  });

  it("resolves the URL: defaults, old CTOR-step links, collapsed, Kéo lên, row", () => {
    expect(resolveSelection(REPORT, {})).toEqual({ tab: "san-pham", stream: "product_card", metric: "ctor", direction: "down", row: null });
    expect(resolveSelection(REPORT, { stream: "the-san-pham", metric: "them-gio" }).metric).toBe("ctor");
    expect(resolveSelection(REPORT, { stream: "video", metric: "aov" }).metric).toBe("ctr");
    expect(resolveSelection(REPORT, { tab: "san-pham", stream: "dong" }).stream).toBeNull();
    const sel = resolveSelection(REPORT, { stream: "tab-cua-hang", metric: "aov", huong: "len", row: "x" });
    expect(sel).toEqual({ tab: "san-pham", stream: "shop_tab", metric: "aov", direction: "up", row: "x" });
    expect(resolveSelection(REPORT, queryOf(analysisHref(sel)))).toEqual(sel);
  });

  it("every sample table reconciles to its cell: listed rows + closing rows = the cell's ₫/day", () => {
    for (const [s, byMetric] of Object.entries(RANKINGS)) {
      for (const [m, envelope] of Object.entries(byMetric ?? {})) {
        const r = envelope!.ranking;
        const listed = [...r.down, ...r.up].reduce((sum, row) => sum + row.gmv_per_day, 0);
        const closing = r.closing.few.gmv_per_day + r.closing.others.gmv_per_day + r.closing.mix.gmv_per_day;
        expect(listed + closing, `${s} × ${m}`).toBeCloseTo(r.stream_factor_gmv, 6);
        const cell = REPORT.channels.find((c) => c.channel === s)!.comparison.factors.find((f) => f.factor === m)!;
        expect(r.stream_factor_gmv).toBe(cell.contribution);
      }
    }
  });

  it("the sample is the Quyết định sample's shop: every sample card's product is ranked", () => {
    const ids = new Set(Object.values(RANKINGS).flatMap((b) => Object.values(b ?? {}).flatMap((e) => [...e!.ranking.down, ...e!.ranking.up].map((r) => r.id))));
    for (const card of SAMPLE_CARDS) {
      const item = sampleDecision(card, Date.now());
      expect(ids.has(item.recommendation.diagnosis!.tiktok_product_id!), card.sku).toBe(true);
    }
  });

  it("joins a row to a card by product and metric; a card links back to its row", () => {
    const items = SAMPLE_CARDS.map((c) => sampleDecision(c, Date.now()));
    const cards = indexCards(items);
    expect(cards.find(SM012, "ctor")?.id).toBe("sample-sm-012");
    expect(cards.find(SM012, "ctr")).toBeNull();
    expect(cards.find(sampleProductId("SR-007"), "ctr")?.proposal).toBe("Ảnh bìa · +1,4 tr ₫/tháng");
    expect(cards.countFor("ctor")).toBe(4);
    expect(decisionCardHref("sample-sm-012")).toBe("/decisions?tab=de-xuat&the=sample-sm-012");
    expect(analysisHrefForDecision(items[0])).toBe(`/analytics?tab=san-pham&stream=the-san-pham&metric=ctor&row=${SM012}`);
  });

  it("Khuyến mãi and Lịch sale read the report's promotions and daily GMV", () => {
    const promo = promoView(REPORT);
    expect(promo.stats.map((s) => s.k)).toEqual(["Flash sale", "Giảm thật trung bình", "Voucher"]);
    expect(promo.stats[0].v).toBe("8/60 ngày");
    expect(promo.stats[1].v).toBe("−9 %");
    expect(promo.rows.find((r) => r.sku === "SM-012")).toMatchObject({ shallow: true, depth: "−2 % (quá nông)" });
    const calendar = calendarView(REPORT)!;
    expect(calendar.bars).toHaveLength(60);
    expect(calendar.first).toBe("08/08");
    expect(calendar.middle).toBe("07/09 · bắt đầu 30 ngày gần đây");
    expect(calendar.tiles.map((t) => t.title)).toEqual(["9.9", "Flash sale 20/09", "Sắp tới"]);
    expect(calendar.tiles[2].text).toBe("10.10, 11.11");
    expect(calendarView({ ...REPORT, daily_gmv: undefined })).toBeNull();
  });
});

describe("Phân tích view", () => {
  it("opens Thẻ sản phẩm on its weakest cell; Tab cửa hàng is collapsed with its weakest", async () => {
    renderView();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/^Thẻ sản phẩm: CTOR giảm/);
    expect(screen.getByTestId("mock-data-notice")).toBeInTheDocument();
    expect(screen.getByTestId("juli-suggestion")).toHaveTextContent("✦ Juli gợi ý · CTOR kéo GMV −250k ₫/ngày");
    expect(await screen.findByRole("link", { name: "Xem 4 đề xuất ›" })).toHaveAttribute("href", "/decisions?tab=de-xuat&nhom=ctor");
    expect(screen.getByTestId("pa-caption")).toHaveTextContent("Sản phẩm:Thẻ sản phẩm · Tab cửa hàng|Nội dung:Video · LIVE|Liên kết:chỉ theo dõi ởTrang chủ ›");
    expect(within(stream("Thẻ sản phẩm")).getByRole("button", { name: "Thu gọn" })).toHaveAttribute("aria-expanded", "true");
    expect(within(stream("Tab cửa hàng")).getByText("Yếu nhất: AOV −31k ₫/ngày")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^CTOR · Thẻ sản phẩm/ })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByRole("heading", { name: "5 sản phẩm kéo CTOR xuống" })).toBeInTheDocument();
    expect(screen.getByTestId("ranking-total")).toHaveTextContent("Tổng · bằng số của ô CTOR−250k ₫/ngày");
  });

  it("only one stream is open; opening Tab cửa hàng collapses Thẻ sản phẩm", async () => {
    const { spy } = renderView();
    await userEvent.click(within(stream("Tab cửa hàng")).getByRole("button", { name: "Mở" }));
    expect(within(stream("Thẻ sản phẩm")).getByRole("button", { name: "Mở" })).toBeInTheDocument();
    expect(spy).toHaveBeenLastCalledWith("/analytics?tab=san-pham&stream=tab-cua-hang&metric=aov");
    expect(await screen.findByRole("heading", { name: "1 sản phẩm kéo AOV xuống" })).toBeInTheDocument();
  });

  it("a clicked cell re-ranks the table and the URL follows; GMV/ngày is not clickable", async () => {
    const { spy } = renderView();
    await userEvent.click(screen.getByRole("button", { name: /^AOV · Thẻ sản phẩm/ }));
    expect(spy).toHaveBeenLastCalledWith("/analytics?tab=san-pham&stream=the-san-pham&metric=aov");
    expect(await screen.findByRole("heading", { name: "2 sản phẩm kéo AOV xuống" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^GMV\/ngày · Thẻ sản phẩm/ })).toBeDisabled();
  });

  it("rows expand in place with CTOR's two steps, SKU orders and the proposal", async () => {
    renderView();
    await screen.findByTestId("ranking-table");
    const sm = rowOf("Son môi số 12");
    await userEvent.click(within(sm).getByRole("button", { expanded: false }));
    expect(within(rowOf("Son môi số 12")).getByText("Hai bước của CTOR")).toBeInTheDocument();
    expect(within(rowOf("Son môi số 12")).getByText("Thêm giỏ/bấm +6k ₫ · Đơn/thêm giỏ −118k ₫")).toBeInTheDocument();
    expect(within(rowOf("Son môi số 12")).getByText("217 → 162")).toBeInTheDocument();
    expect(within(rowOf("Son môi số 12")).getByText("Mô tả · +2,1 tr ₫/tháng")).toBeInTheDocument();
  });

  it("rows with a card link to it; the others say Chưa có đề xuất", async () => {
    renderView();
    await screen.findByTestId("ranking-table");
    await waitFor(() => expect(within(rowOf("Son môi số 12")).getByRole("link", { name: "Xem đề xuất ›" })).toHaveAttribute("href", "/decisions?tab=de-xuat&the=sample-sm-012"));
    expect(within(rowOf("Kem dưỡng ẩm ceramide")).getByRole("link", { name: "Xem đề xuất ›" })).toHaveAttribute("href", "/decisions?tab=de-xuat&the=sample-kd-030");
    expect(within(rowOf("Sữa rửa mặt amino")).getByText("Chưa có đề xuất")).toBeInTheDocument();
  });

  it("Kéo lên, Còn lại · 3 dòng", async () => {
    renderView();
    await screen.findByTestId("ranking-table");
    await userEvent.click(screen.getByRole("button", { name: "Kéo lên" }));
    expect(screen.getByRole("heading", { name: "1 sản phẩm kéo CTOR lên" })).toBeInTheDocument();
    expect(rowOf("Toner rau má 200ml")).toBeTruthy();
    const rest = screen.getByRole("button", { name: /Còn lại · 3 dòng/ });
    await userEvent.click(rest);
    expect(screen.getByText("2 sản phẩm ít đơn")).toBeInTheDocument();
    expect(screen.getByText("Thay đổi cơ cấu sản phẩm")).toBeInTheDocument();
  });

  it("arrives on a row from a card: stream, metric and row expanded; a Kéo lên row switches the table", async () => {
    renderView(`/analytics?tab=san-pham&stream=the-san-pham&metric=ctor&row=${SM012}`);
    await screen.findByTestId("ranking-table");
    expect(within(rowOf("Son môi số 12")).getByRole("button", { expanded: true })).toBeInTheDocument();
    renderView(`/analytics?tab=san-pham&stream=the-san-pham&metric=ctor&row=${sampleProductId("TN-021")}`);
    expect(await screen.findByRole("heading", { name: "1 sản phẩm kéo CTOR lên" })).toBeInTheDocument();
  });

  it("Nội dung: video rows, greyed cells, Xem sản phẩm được gắn › opens that product's row", async () => {
    const { spy } = renderView("/analytics?tab=noi-dung");
    expect(screen.queryByTestId("juli-suggestion")).toBeNull();
    expect(screen.getByRole("button", { name: /^CTOR · Video của người bán/ })).toBeDisabled();
    expect(await screen.findByRole("heading", { name: "Video tác động CTR nhiều nhất" })).toBeInTheDocument();
    const v1 = rowOf("Mặt nạ đất sét: trước và sau");
    expect(v1).toHaveTextContent("Đăng 02/09 · gắn MN-015");
    await userEvent.click(within(v1).getByRole("link", { name: "Xem sản phẩm được gắn ›" }));
    expect(spy).toHaveBeenLastCalledWith(`/analytics?tab=san-pham&stream=the-san-pham&metric=ctor&row=${sampleProductId("MN-015")}`);
    expect(await screen.findByRole("tab", { name: "Sản phẩm" })).toHaveAttribute("aria-selected", "true");
    expect(within(rowOf("Mặt nạ đất sét 100g")).getByRole("button", { expanded: true })).toBeInTheDocument();
  });

  it("Khuyến mãi and Lịch sale start collapsed; ⓘ Cách tính toggles the explanation", async () => {
    renderView();
    const promo = screen.getByTestId("more-khuyen-mai");
    expect(within(promo).getByRole("button", { name: "Xem thêm" })).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(within(promo).getByRole("button", { name: "Xem thêm" }));
    expect(within(promo).getByText("Giảm thật trung bình")).toBeInTheDocument();
    await userEvent.click(within(screen.getByTestId("more-lich-sale")).getByRole("button", { name: "Xem thêm" }));
    expect(screen.getByText(/gấp .* lần ngày thường/)).toBeInTheDocument();
    expect(screen.queryByText(/Số trung bình mỗi ngày/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Cách tính" }));
    expect(screen.getByText(/Số trung bình mỗi ngày/)).toBeInTheDocument();
  });

  it("the old Ví dụ panel, hero list and explanatory paragraph are gone", async () => {
    renderView();
    await screen.findByTestId("ranking-table");
    expect(screen.queryByTestId("detail-panel")).toBeNull();
    expect(screen.queryByText(/Bấm một chỉ số để xem/)).toBeNull();
    expect(screen.queryByText(/Sản phẩm chủ lực/)).toBeNull();
  });
});

describe("Đề xuất ← Phân tích", () => {
  function QdHarness({ initial }: { initial: string }) {
    const [href, setHref] = useState(initial);
    const p = new URLSearchParams(href.split("?")[1] ?? "");
    const query: QdQuery = { tab: resolveTab(p.get("tab")), run: null, rulesOpen: false, focusCard: p.get("the"), focusMetric: p.get("nhom") };
    const [clients] = useState(() => createSampleQdClients({ stepMs: 0 }));
    return <SampleQuyetDinh clients={clients} onNavigate={setHref} query={query} />;
  }

  it("the=<card> outlines that card for 3 s; each card links back with Xem phân tích ›", async () => {
    vi.spyOn(window, "setTimeout");
    render(<QdHarness initial="/decisions?tab=de-xuat&the=sample-sm-012" />);
    const card = await waitFor(() => {
      const found = document.querySelector('[data-decision-id="sample-sm-012"]');
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    await waitFor(() => expect(card).toHaveAttribute("data-focused", "true"));
    expect(card.className).toContain("qv-card--focus");
    expect(within(card).getByRole("link", { name: "Xem phân tích ›" })).toHaveAttribute(
      "href",
      `/analytics?tab=san-pham&stream=the-san-pham&metric=ctor&row=${SM012}`,
    );
    expect(window.setTimeout).toHaveBeenCalledWith(expect.any(Function), 3000);
  });

  it("nhom=ctor outlines the CTOR group", async () => {
    render(<QdHarness initial="/decisions?tab=de-xuat&nhom=ctor" />);
    await waitFor(() => expect(document.querySelector(".qv-group--focus")).not.toBeNull());
    expect(document.querySelector(".qv-group--focus")?.getAttribute("data-group-key")).toBe("PRODUCT_CARD:page");
  });
});

describe("Phân tích — signed in", () => {
  it("reads the open cell's ranking and the decisions with the token and the acting shop", async () => {
    const fetchRanking = vi.fn().mockResolvedValue(CTOR);
    const fetchDecisions = vi.fn().mockResolvedValue([]);
    render(
      <SignedInPhanTich
        envelope={sampleEnvelope()}
        fetchDecisions={fetchDecisions}
        fetchRanking={fetchRanking}
        query={{}}
        shopId="shop-1"
        token="token-1"
      />,
    );
    expect(await screen.findByTestId("ranking-table")).toBeInTheDocument();
    expect(fetchRanking).toHaveBeenCalledWith({ token: "token-1", shopId: "shop-1", stream: "product_card", metric: "ctor" });
    expect(fetchDecisions).toHaveBeenCalledWith({ token: "token-1", shopId: "shop-1" });
    expect(screen.queryByTestId("mock-data-notice")).toBeNull();
    expect(within(rowOf("Son môi số 12")).getByText("Chưa có đề xuất")).toBeInTheDocument();
  });

  it("a decisions failure only hides the links", async () => {
    render(
      <SignedInPhanTich
        envelope={sampleEnvelope()}
        fetchDecisions={vi.fn().mockRejectedValue(new Error("down"))}
        fetchRanking={vi.fn().mockResolvedValue(CTOR)}
        query={{}}
        shopId="s"
        token="t"
      />,
    );
    expect(await screen.findByTestId("ranking-table")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Xem đề xuất ›" })).toBeNull();
  });

  it("404 → Chưa có bảng xếp hạng; a failure offers Thử lại", async () => {
    const fetchRanking = vi.fn().mockRejectedValueOnce(new Error("x")).mockResolvedValue(null);
    render(
      <SignedInPhanTich envelope={sampleEnvelope()} fetchDecisions={vi.fn().mockResolvedValue([])} fetchRanking={fetchRanking} query={{}} shopId="s" token="t" />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Thử lại" }));
    expect(await screen.findByText("Chưa có bảng xếp hạng cho chỉ số này")).toBeInTheDocument();
  });

  it("the rankings client sends bearer + X-Shop-Id, and maps 404 to null", async () => {
    const ok = vi.fn().mockResolvedValue(new Response(JSON.stringify(CTOR), { status: 200 }));
    await expect(fetchMetricRanking({ token: "t", shopId: "s", stream: "seller_live", metric: "ctor", fetchImpl: ok })).resolves.toEqual(CTOR);
    const [url, init] = ok.mock.calls[0];
    expect(url).toBe(`${DEMO_RANKINGS_API_PATH}?stream=seller_live&metric=ctor`);
    expect(init.headers).toMatchObject({ Authorization: "Bearer t", "X-Shop-Id": "s" });
    const missing = vi.fn().mockResolvedValue(new Response("{}", { status: 404 }));
    await expect(fetchMetricRanking({ token: "t", shopId: "s", stream: "product_card", metric: "aov", fetchImpl: missing })).resolves.toBeNull();
  });

  it("/analytics reads the report once, through the shell's useShopReport", async () => {
    window.sessionStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "token-1", tokenType: "bearer" }));
    window.sessionStorage.setItem(ACTIVE_SHOP_STORAGE_KEY, JSON.stringify({ id: "shop-1", name: "Shop Thật" }));
    searchParams.set("tab", "noi-dung");
    const loadAnalysis = vi.fn().mockResolvedValue(sampleEnvelope());
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
    expect(urls).toContain(`${DEMO_RANKINGS_API_PATH}?stream=seller_video&metric=ctr`);
    expect(urls.some((u) => u.startsWith("/v1/demo/analysis?") || u === "/v1/demo/analysis")).toBe(false);
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
    expect(await screen.findByTestId("mock-data-notice")).toHaveTextContent("Cửa hàng Mẫu Hoa Mai");
    expect(await screen.findByTestId("ranking-table")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
