import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { fakeApi, kolSection, metricView } from "../../../lib/shopee-analytics/__tests__/fixtures";
import { readMetricParams, sortRows } from "../../../lib/shopee-analytics/metric-view";
import { PhanTichPageView, periodQuery } from "../phan-tich-view";
import { params, renderWith } from "./harness";

const q = (href: string | null) => new URLSearchParams((href ?? "").split("?")[1] ?? "");

describe("Phân tích (board B)", () => {
  it("leads with the number: metric, change, weakest luồng, products pulling down", async () => {
    renderWith(<PhanTichPageView params={params("metric=ctr")} />, fakeApi());
    expect(await screen.findByRole("heading", { level: 1, name: "CTR ▼ 20 % · Thẻ sản phẩm · 2 sản phẩm kéo xuống" })).toBeInTheDocument();
  });

  it("asks the API for the metric, luồng and product of the URL, and the old kpi / src names still work", async () => {
    const api = fakeApi();
    renderWith(<PhanTichPageView params={params("metric=aov&channel=video&product=GL-001&ky=7d")} />, api);
    await screen.findByTestId("pt-channels");
    expect(api.calls.some((c) => c.startsWith("metricView:") && c.includes('"metric":"aov"') && c.includes('"channel":"video"') && c.includes('"productId":"GL-001"') && c.includes('"period":"7d"'))).toBe(true);
    expect(readMetricParams(params("kpi=bien&src=ads&focus=X1"))).toEqual({ metric: "margin", channel: "ads_product", product: "X1", mode: "total" });
    expect(readMetricParams(params("metric=nope&channel=zzz"))).toMatchObject({ metric: "gmv", channel: null });
  });

  it("shows all seven metric chips, the selected one with its shift, each linking to its own metric", async () => {
    renderWith(<PhanTichPageView params={params("metric=ctr")} />, fakeApi());
    for (const m of ["views", "ctr", "ctor", "aov", "orders", "gmv", "margin"]) expect(await screen.findByTestId(`pt-chip-${m}`)).toBeInTheDocument();
    const ctr = screen.getByTestId("pt-chip-ctr");
    expect(ctr).toHaveAttribute("aria-current", "true");
    expect(ctr).toHaveTextContent("▼ 20 %");
    expect(q(screen.getByTestId("pt-chip-aov").getAttribute("href")).get("metric")).toBe("aov");
    expect(screen.getByTestId("pt-chip-gmv")).not.toHaveTextContent("%");
  });

  it("Theo luồng: this period, previous, change, GMV affected, DVHT rows name their source", async () => {
    renderWith(<PhanTichPageView params={params("metric=ctr")} />, fakeApi());
    const row = await screen.findByTestId("pt-channel-the_san_pham");
    expect(row).toHaveTextContent("Thẻ sản phẩm4,00%5,00%▼ 20 %−2,00 trĐề xuất (3) ›");
    expect(screen.getByTestId("pt-channel-ads_product")).toHaveTextContent("DVHT Sản phẩmBáo cáo DVHT");
    expect(screen.getByTestId("pt-channel-live")).toHaveTextContent("Live——");
    expect(screen.getByTestId("pt-channel-live")).toHaveTextContent("Tự tạo ›");
  });

  it("every luồng and product row has as many cells as the header, so the CTA stays in its column (a null change once shifted it left)", async () => {
    renderWith(<PhanTichPageView params={params("metric=ctr")} />, fakeApi());
    await screen.findByTestId("pt-channels");
    const head = screen.getByTestId("pt-channels").querySelector(".jp-grid--head")!;
    const rows = screen.getAllByTestId(/^pt-channel-/).filter((e) => e.classList.contains("jp-grid"));
    expect(rows.length).toBeGreaterThan(1);
    expect(screen.getByTestId("pt-channel-live")).toHaveTextContent("Live——");
    for (const row of rows) expect(row.children.length).toBe(head.children.length);
    const pHead = screen.getByTestId("pt-products").querySelector(".jp-grid--head")!;
    for (const row of screen.getAllByTestId(/^pt-product-/).filter((e) => e.classList.contains("jp-grid"))) expect(row.children.length).toBe(pHead.children.length);
  });

  it("CTAs: Đề xuất (n) opens Quyết định filtered by metric and product; Tự tạo opens the builder with the product", async () => {
    renderWith(<PhanTichPageView params={params("metric=ctr&ky=7d")} />, fakeApi());
    const withCards = within(await screen.findByTestId("pt-product-GL-001")).getByRole("link", { name: "Đề xuất (2) ›" });
    const p = q(withCards.getAttribute("href"));
    expect(withCards.getAttribute("href")).toMatch(/^\/decisions\?/);
    expect([p.get("tab"), p.get("metric"), p.get("product"), p.get("ky")]).toEqual(["de-xuat", "ctr", "GL-001", "7d"]);
    const none = within(screen.getByTestId("pt-product-XM-003")).getByRole("link", { name: "Tự tạo ›" });
    const b = q(none.getAttribute("href"));
    expect([b.get("tu-tao"), b.get("sp")]).toEqual(["1", "XM-003"]);
  });

  it("Theo sản phẩm sorts by GMV affected (biggest loss first) or by the change", async () => {
    renderWith(<PhanTichPageView params={params("metric=ctr")} />, fakeApi());
    const ids = () => screen.getAllByTestId(/^pt-product-/).map((e) => e.getAttribute("data-testid"));
    await screen.findByTestId("pt-products");
    expect(ids()).toEqual(["pt-product-GL-001", "pt-product-BEP-S5", "pt-product-XM-003"]);
    fireEvent.change(screen.getByRole("combobox", { name: "Xếp theo" }), { target: { value: "change" } });
    await waitFor(() => expect(ids()[0]).toBe("pt-product-GL-001"));
    const rows = metricView().products;
    expect(sortRows(rows, "change").map((r) => r.product_id)).toEqual(["GL-001", "BEP-S5", "XM-003"]);
  });

  it("Trung bình / ngày divides the sums by the days and leaves rates alone", async () => {
    const api = fakeApi({
      metricView: metricView({
        metric: "gmv",
        total: { key: "total", now: 3_000_000, prev: 6_000_000, change: -0.5, impact: -3_000_000, cards: 0 },
        channels: [{ key: "video", now: 3_000_000, prev: 6_000_000, change: -0.5, impact: -3_000_000, cards: 0 }],
        products: [],
      }),
    });
    const { unmount } = renderWith(<PhanTichPageView params={params("metric=gmv&cach=tb")} />, api);
    const row = await screen.findByTestId("pt-channel-video");
    expect(row).toHaveTextContent("100.000đ200.000đ▼ 50 %−100.000đ");
    expect(screen.getByRole("link", { name: "Trung bình / ngày" })).toHaveAttribute("aria-current", "true");
    unmount();
    renderWith(<PhanTichPageView params={params("metric=ctr&cach=tb")} />, fakeApi());
    expect(await screen.findByTestId("pt-channel-the_san_pham")).toHaveTextContent("4,00%5,00%");
  });

  it("the mode link keeps the metric and the window", async () => {
    renderWith(<PhanTichPageView params={params("metric=ctor&ky=90d")} />, fakeApi());
    const avg = q((await screen.findByRole("link", { name: "Trung bình / ngày" })).getAttribute("href"));
    expect([avg.get("metric"), avg.get("ky"), avg.get("cach")]).toEqual(["ctor", "90d", "tb"]);
  });

  it("the KOL section is always there: totals, split, rows with change and CTA", async () => {
    renderWith(<PhanTichPageView params={params()} />, fakeApi({ kolSection: kolSection() }));
    const totals = await screen.findByTestId("pt-kol-totals");
    expect(totals).toHaveTextContent("Lượt nhấp 100Đơn 10GMV 1,20 trVideo KOL 1,03 trLive KOL 80.000đKhác 90.000đ");
    const row = screen.getByTestId("pt-kol-k1-GL-001");
    expect(row).toHaveTextContent("@kol_mot");
    expect(row).toHaveTextContent("+150.000đ");
    expect(row).toHaveTextContent("▲ 28 %");
    expect(within(row).getByRole("link", { name: "Đề xuất (1) ›" })).toBeInTheDocument();
    const second = screen.getByTestId("pt-kol-k2-XM-003");
    expect(second).toHaveTextContent("−20.000đ");
    expect(within(second).getByRole("link", { name: "Tự tạo ›" })).toBeInTheDocument();
  });

  it("has no critical list, legend, notices or KOL tab", async () => {
    const { container } = renderWith(<PhanTichPageView params={params("tab=kol")} />, fakeApi());
    await screen.findByTestId("pt-products");
    expect(screen.queryByTestId("sa-critical-list")).toBeNull();
    expect(screen.queryByTestId("sa-pt-tabs")).toBeNull();
    expect(container.querySelector(".sa-notice, .sa-info")).toBeNull();
  });

  it("period links keep metric, luồng and product", () => {
    const p = periodQuery(params("metric=aov&channel=video&product=P1&cach=tb&ky=7d"), { query: { period: "90d" }, compare: true });
    expect([p.get("metric"), p.get("channel"), p.get("product"), p.get("cach"), p.get("ky")]).toEqual(["aov", "video", "P1", "tb", "90d"]);
  });
});
