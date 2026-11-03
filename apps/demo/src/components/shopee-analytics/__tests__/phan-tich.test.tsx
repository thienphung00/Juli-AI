import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { fakeApi, critical } from "../../../lib/shopee-analytics/__tests__/fixtures";
import { PhanTichPageView, chartOf } from "../phan-tich-view";
import { params, renderWith, textOf } from "./harness";

const q = (href: string | null) => new URLSearchParams((href ?? "").split("?")[1] ?? "");

describe("Phân tích", () => {
  it("lists the critical items ranked by ₫ at stake, biggest first", async () => {
    renderWith(<PhanTichPageView params={params()} />, fakeApi());
    expect(await screen.findByRole("heading", { level: 1, name: "3 chỉ số cần chú ý" })).toBeInTheDocument();
    const ids = screen.getAllByTestId(/^sa-item-/).map((e) => e.getAttribute("data-testid"));
    expect(ids).toEqual(["sa-item-flow:the_san_pham_khac:ctor", "sa-item-product:GL-001:bien", "sa-item-product:XM-003:roas"]);
    const first = screen.getByTestId("sa-item-flow:the_san_pham_khac:ctor");
    expect(first).toHaveTextContent("−300.000đ/ngày");
    expect(first).toHaveTextContent("−9.000.000đ/tháng");
  });

  it("totals the ₫ at stake per day and per month", async () => {
    renderWith(<PhanTichPageView params={params()} />, fakeApi());
    const bar = await screen.findByTestId("sa-at-stake");
    expect(bar).toHaveTextContent("Tổng ₫ có nguy cơ: −470.000đ/ngày (−14.100.000đ/tháng)");
  });

  it("each item draws the band chart, the deviation and the funnel stage of its cause", async () => {
    renderWith(<PhanTichPageView params={params()} />, fakeApi());
    const flow = await screen.findByTestId("sa-item-flow:the_san_pham_khac:ctor");
    expect(within(flow).getByTestId("sa-band-flow:the_san_pham_khac:ctor")).toBeInTheDocument();
    expect(flow).toHaveTextContent("Thấp hơn dải 1,00 điểm");
    expect(flow).toHaveTextContent("Dải bình thường 8,00%–9,00%");
    expect(flow).toHaveTextContent("Khách bấm vào nhưng ít đặt đơn.");
    const stages = flow.querySelectorAll(".sa-stage--on");
    expect(stages).toHaveLength(1);
    expect(stages[0]).toHaveTextContent("CTOR");

    const margin = screen.getByTestId("sa-item-product:GL-001:bien");
    expect(margin).toHaveTextContent("8,0%");
    expect(margin).toHaveTextContent("Thấp hơn mục tiêu 2,0 điểm");
    expect(margin).toHaveTextContent("giá vốn giả định (1/3 giá)");
    expect(margin.querySelector(".sa-stage--on")).toHaveTextContent("Biên");

    const roas = screen.getByTestId("sa-item-product:XM-003:roas");
    expect(roas).toHaveTextContent("đơn đã đặt");
    expect(roas).toHaveTextContent("Thấp hơn hoà vốn 0,9");
  });

  it("links to the Xếp hạng row (kpi, src, focus, from=phan-tich, card) and to the card", async () => {
    renderWith(<PhanTichPageView params={params()} />, fakeApi());
    const flow = await screen.findByTestId("sa-item-flow:the_san_pham_khac:ctor");
    const rank = within(flow).getByRole("link", { name: "Xem xếp hạng ›" });
    expect(rank.getAttribute("href")?.split("?")[0]).toBe("/xep-hang");
    expect(Object.fromEntries(q(rank.getAttribute("href")))).toEqual({ kpi: "ctor", src: "the_san_pham", focus: "the_san_pham_khac", from: "phan-tich", card: "c_xm_disc" });
    const card = within(flow).getByRole("link", { name: "Xem đề xuất ›" });
    expect(Object.fromEntries(q(card.getAttribute("href")))).toEqual({ the: "c_xm_disc", from: "phan-tich", row: "flow:the_san_pham_khac:ctor" });
    const margin = screen.getByTestId("sa-item-product:GL-001:bien");
    expect(within(margin).getByText("Chưa có đề xuất")).toBeInTheDocument();
    expect(Object.fromEntries(q(within(margin).getByRole("link", { name: "Xem xếp hạng ›" }).getAttribute("href")))).toEqual({ kpi: "bien", src: "all", focus: "GL-001", from: "phan-tich" });
  });

  it("a ROAS item opens the ads ranking (kpi roas is not a ranking tab)", async () => {
    renderWith(<PhanTichPageView params={params()} />, fakeApi());
    const roas = await screen.findByTestId("sa-item-product:XM-003:roas");
    const href = within(roas).getByRole("link", { name: "Xem xếp hạng ›" }).getAttribute("href");
    expect(q(href).get("kpi")).toBe("gmv");
    expect(q(href).get("src")).toBe("ads");
  });

  it("offers the first card in the Juli bar", async () => {
    renderWith(<PhanTichPageView params={params()} />, fakeApi());
    const bar = await screen.findByTestId("sa-at-stake");
    expect(within(bar).getByRole("link", { name: "Xem 1 đề xuất ›" }).getAttribute("href")).toContain("the=c_xm_disc");
  });

  it("filters by metric group", async () => {
    renderWith(<PhanTichPageView params={params()} />, fakeApi());
    const user = userEvent.setup();
    await screen.findByTestId("sa-critical-list");
    await user.click(screen.getByRole("button", { name: "Quảng cáo" }));
    expect(screen.getAllByTestId(/^sa-item-/)).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "AOV" }));
    expect(screen.getByTestId("sa-critical-empty")).toHaveTextContent("Không có chỉ số cần chú ý ở nhóm này");
    await user.click(screen.getByRole("button", { name: "Biên và giá sàn" }));
    expect(screen.getAllByTestId(/^sa-item-/)).toHaveLength(1);
  });

  it("folds items inside their reference into 'Trong dải bình thường' and keeps them out of the total", async () => {
    renderWith(<PhanTichPageView params={params()} />, fakeApi());
    const user = userEvent.setup();
    const box = await screen.findByTestId("sa-in-band");
    expect(box).toHaveTextContent("1 mục · không tính vào ₫ có nguy cơ");
    expect(screen.queryByTestId("sa-ok-flow:video:ctr")).toBeNull();
    await user.click(within(box).getByRole("button", { name: "Xem thêm" }));
    expect(screen.getByTestId("sa-ok-flow:video:ctr")).toBeInTheDocument();
    expect(screen.getByTestId("sa-at-stake")).toHaveTextContent("−470.000đ/ngày");
  });

  it("shows the notes (missing target, assumed cost, missing history) as they come", async () => {
    renderWith(<PhanTichPageView params={params()} />, fakeApi({ critical: critical({ notes: [{ code: "margin_target_missing", message: "Chưa đặt mục tiêu biên." }, { code: "band_missing:live", message: "Chưa đủ lịch sử để lập dải bình thường cho Live." }] }) }));
    expect(await screen.findByTestId("sa-note-margin_target_missing")).toHaveTextContent("Chưa đặt mục tiêu biên.");
    expect(screen.getByTestId("sa-note-band_missing:live")).toBeInTheDocument();
  });

  it("empty: no item says so, with no total bar", async () => {
    renderWith(<PhanTichPageView params={params()} />, fakeApi({ critical: critical({ items: [], in_band: [], total_at_stake_per_day: 0, notes: [] }) }));
    expect(await screen.findByTestId("sa-critical-empty")).toHaveTextContent("Chưa có chỉ số nào cần chú ý");
    expect(screen.queryByTestId("sa-at-stake")).toBeNull();
  });

  it("the band chart puts the dot on the item's own axis", () => {
    const item = critical().items[0]!;
    const c = chartOf(item)!;
    expect(c.band).not.toBeNull();
    expect(c.tick).toBeNull();
    expect(c.dot!).toBeLessThan(c.band!.left);
    const target = chartOf(critical().items[1]!)!;
    expect(target.tick).not.toBeNull();
    expect(target.band).toBeNull();
  });

  it("never draws a buyer field", async () => {
    const { container } = renderWith(<PhanTichPageView params={params()} />, fakeApi());
    await screen.findByTestId("sa-critical-list");
    expect(textOf(container).toLowerCase()).not.toContain("buyer");
  });
});
