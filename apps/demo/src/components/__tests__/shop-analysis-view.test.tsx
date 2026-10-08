import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SignedInShopAnalysis } from "../shop-analysis/signed-in-shop-analysis";
import { SAMPLE_SHOP_ANALYSIS } from "../shop-analysis/sample-shop-analysis";
import { ShopAnalysisView } from "../shop-analysis/shop-analysis-view";
import { fetchShopAnalysis } from "../../lib/shop-analysis/api-client";
import { storeActiveShop } from "../../lib/shop-session";
import type { ShopAnalysisEnvelope } from "../../lib/shop-analysis/types";

vi.mock("next/navigation", () => ({
  usePathname: () => "/analytics",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

function fixture(): ShopAnalysisEnvelope {
  return structuredClone(SAMPLE_SHOP_ANALYSIS);
}

/** The same report with Tab Cửa hàng absent from every channel list. */
function withoutShopTab(): ShopAnalysisEnvelope {
  const envelope = fixture();
  const report = envelope.report;
  report.channels = report.channels.filter((r) => r.channel !== "shop_tab");
  report.timelines = report.timelines.filter((t) => t.channel !== "shop_tab");
  for (const profile of report.profiles) {
    profile.channels = profile.channels.filter((r) => r.channel !== "shop_tab");
    delete profile.gmv_share.shop_tab;
  }
  return envelope;
}

const SHOP = { id: "shop-1", name: "Shop của tôi" };

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
});

describe("ShopAnalysisView — renders the ADR-108 report from its JSON", () => {
  it("renders every section, in order, with TikTok's channel names", () => {
    render(<ShopAnalysisView envelope={fixture()} />);

    const titles = screen
      .getAllByRole("heading", { level: 2 })
      .map((h) => h.textContent);
    expect(titles).toEqual([
      "GMV trung bình mỗi ngày, chia theo 5 kênh",
      "Phễu của từng kênh: từ lượt hiển thị sản phẩm đến GMV",
      "Năm sản phẩm chủ lực",
      "Dòng thời gian sự kiện",
      "Flash sale, giảm giá và voucher",
      "Chỉ số trung bình của shop",
      "Cách tính",
    ]);

    const split = screen.getByRole("region", { name: "GMV trung bình mỗi ngày theo kênh" });
    for (const name of [
      "Thẻ sản phẩm của người bán",
      "Tab Cửa hàng *",
      "Video của người bán",
      "LIVE của người bán",
      "Liên kết",
      "Tất cả kênh (toàn shop)",
    ]) {
      expect(within(split).getByRole("rowheader", { name })).toBeInTheDocument();
    }
    expect(screen.getAllByText("GMV/ngày · 30 ngày gần đây").length).toBeGreaterThan(0);
  });

  it("prints Vietnamese numbers and dd/mm/yyyy windows", () => {
    render(<ShopAnalysisView envelope={fixture()} />);
    expect(screen.getByText(/30 ngày gần đây: 07\/09\/2026–06\/10\/2026/)).toBeInTheDocument();
    // Shop-wide total GMV per day, "." thousands and the ₫ sign.
    const total = screen.getByRole("rowheader", { name: "Tất cả kênh (toàn shop)" }).closest("tr");
    expect(total).toHaveTextContent(/\d{1,3}(\.\d{3})+ ₫/);
  });

  it("shows each channel's funnel from Lượt hiển thị sản phẩm to GMV", () => {
    render(<ShopAnalysisView envelope={fixture()} />);
    const card = screen.getByRole("article", { name: "Phễu: Thẻ sản phẩm của người bán" });
    for (const label of [
      "Lượt hiển thị sản phẩm",
      "CTR (Tỷ lệ nhấp)",
      "Tỷ lệ thêm vào giỏ hàng",
      "Đơn hàng SKU",
      "CTOR",
      "AOV (SKU)",
      "GMV",
    ]) {
      expect(within(card).getAllByText(label).length).toBeGreaterThan(0);
    }
    // Tab Cửa hàng has no add-to-cart data: TikTok's own wording.
    const tab = screen.getByRole("article", { name: "Phễu: Tab Cửa hàng" });
    expect(within(tab).getAllByText("TikTok không cung cấp").length).toBe(2);
  });

  it("renders the five hero profiles with all five channels once expanded", async () => {
    const user = userEvent.setup();
    render(<ShopAnalysisView envelope={fixture()} />);
    const heroes = screen.getAllByText(/^Sản phẩm chủ lực \d$/);
    expect(heroes).toHaveLength(5);

    const first = screen.getByRole("article", { name: "Bình giữ nhiệt inox 500ml" });
    expect(within(first).getByText(/Cần xem tiếp:/)).toBeInTheDocument();
    await user.click(within(first).getByRole("button", { name: "Mở rộng" }));
    const table = within(first).getByRole("region", { name: "Phễu theo từng kênh" });
    for (const name of [
      "Thẻ sản phẩm của người bán",
      "Tab Cửa hàng",
      "Video của người bán",
      "LIVE của người bán",
      "Liên kết",
    ]) {
      expect(within(table).getByRole("rowheader", { name })).toBeInTheDocument();
    }
  });

  it("shows the timeline channel picker, promotion lanes and the flash flags", () => {
    render(<ShopAnalysisView envelope={fixture()} />);
    expect(screen.getByRole("group", { name: "Chọn kênh" })).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: "Lịch khuyến mãi trong 60 ngày" }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Flash gần như liên tục").length).toBeGreaterThan(0);
    expect(screen.getByText(/Giá một món phổ biến/)).toBeInTheDocument();
  });

  it("says 'Chưa có dữ liệu' wherever Tab Cửa hàng is missing — never a zero", () => {
    render(<ShopAnalysisView envelope={withoutShopTab()} />);
    const split = screen.getByRole("region", { name: "GMV trung bình mỗi ngày theo kênh" });
    const row = within(split).getByRole("rowheader", { name: "Tab Cửa hàng" }).closest("tr");
    expect(row).toHaveTextContent("Chưa có dữ liệu");
    const card = screen.getByRole("article", { name: "Phễu: Tab Cửa hàng" });
    expect(within(card).getByText("Chưa có dữ liệu")).toBeInTheDocument();
    expect(within(card).queryByText("0 ₫")).not.toBeInTheDocument();
  });

  it("carries no backend field or endpoint names in the visible text", () => {
    const { container } = render(<ShopAnalysisView envelope={fixture()} sample />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/\/v1\/|[a-z]+_[a-z_]+|report\.json|endpoint|undefined|NaN/);
    expect(screen.getByText("Dữ liệu mẫu")).toBeInTheDocument();
  });
});

describe("SignedInShopAnalysis", () => {
  beforeEach(() => {
    storeActiveShop(SHOP);
  });

  it("renders the honest empty state when the shop has no report yet (404)", async () => {
    const loadAnalysis = vi.fn().mockResolvedValue(null);
    render(<SignedInShopAnalysis token="t" loadAnalysis={loadAnalysis} />);
    expect(await screen.findByText("Chưa có báo cáo")).toBeInTheDocument();
    expect(screen.queryByText("Dữ liệu mẫu")).not.toBeInTheDocument();
  });

  it("renders the report for the acting shop, and an error never falls back to the sample", async () => {
    const loadAnalysis = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(fixture());
    render(<SignedInShopAnalysis token="t" loadAnalysis={loadAnalysis} />);
    expect(
      await screen.findByText("Không thể tải báo cáo phân tích cho shop của bạn. Vui lòng thử lại."),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("shop-analysis")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(await screen.findByTestId("shop-analysis")).toBeInTheDocument();
    expect(loadAnalysis).toHaveBeenLastCalledWith(
      expect.objectContaining({ token: "t", shopId: SHOP.id, ranking: "60d" }),
    );
  });
});

describe("fetchShopAnalysis", () => {
  it("sends the bearer token and X-Shop-Id, and maps 404 to null", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response("{}", { status: 404 }));
    await expect(
      fetchShopAnalysis({ token: "tok", shopId: "s1", fetchImpl }),
    ).resolves.toBeNull();
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/v1/demo/analysis");
    expect(init.headers).toMatchObject({ Authorization: "Bearer tok", "X-Shop-Id": "s1" });
  });

  it("passes the ranking, returns the envelope, and rejects a malformed body", async () => {
    const ok = vi.fn().mockResolvedValue(new Response(JSON.stringify(fixture()), { status: 200 }));
    const envelope = await fetchShopAnalysis({ token: "t", shopId: "s", ranking: "30d", fetchImpl: ok });
    expect(ok.mock.calls[0][0]).toBe("/v1/demo/analysis?ranking=30d");
    expect(envelope?.report.channels.length).toBe(5);

    const bad = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    await expect(fetchShopAnalysis({ token: "t", shopId: "s", fetchImpl: bad })).rejects.toThrow();
    const fail = vi.fn().mockResolvedValue(new Response("", { status: 500 }));
    await expect(fetchShopAnalysis({ token: "t", shopId: "s", fetchImpl: fail })).rejects.toThrow();
  });
});
