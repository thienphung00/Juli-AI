import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { channelSplit, fakeApi } from "../../../lib/shopee-analytics/__tests__/fixtures";
import type { ChannelRow, ChannelSplit } from "../../../lib/shopee-analytics/types";
import { TongQuanView } from "../tong-quan";
import { params, renderWith } from "./harness";

/** A TikTok fixture shop (decision #7): the four sources sum to the total, Tab cửa hàng sits outside it. */
function tiktokSplit(): ChannelSplit {
  const base = channelSplit();
  const blank = { views: null, clicks: null, ctr: null, ctor: null, aov: null, gmv: null, orders: null, share: null, prev: null };
  const rows: ChannelRow[] = base.rows.map((r) => {
    if (r.key === "ads" || r.key === "ads_product" || r.key === "ads_shop") return { ...r, ...blank, ad_base: null };
    if (r.key === "organic_shop") return { ...r, orders: 6, ctor: 0.06, aov: 100_000 }; // the API must not be trusted to blank these
    return r;
  });
  return { ...base, rows };
}

describe("W3 U-2 · a TikTok shop's Tổng quan on the shared screen", () => {
  it("names the platform and the sources the TikTok way", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi({ split: tiktokSplit() }), { platform: "tiktok" });
    await screen.findByTestId("sa-channels");
    expect(screen.getByTestId("sa-platform")).toHaveTextContent("TikTok Shop");
    expect(screen.getByTestId("sa-channel-organic_live")).toHaveTextContent("LIVE");
    expect(screen.getByTestId("sa-channel-organic_shop")).toHaveTextContent("Tab cửa hàng");
    expect(screen.getByTestId("sa-channel-ads")).toHaveTextContent("Quảng cáo");
    expect(screen.queryByText("Trang shop")).toBeNull();
    expect(screen.queryByText("DVHT Sản phẩm")).toBeNull();
  });

  it("Tab cửa hàng is last and outside the total; its orders / CTOR / AOV are —", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi({ split: tiktokSplit() }), { platform: "tiktok" });
    await screen.findByTestId("sa-channels");
    const keys = screen.getAllByTestId(/^sa-channel-/).map((el) => el.getAttribute("data-testid")?.replace("sa-channel-", ""));
    expect(keys[keys.length - 1]).toBe("organic_shop");
    const tab = screen.getByTestId("sa-channel-organic_shop");
    expect(tab).toHaveAttribute("data-outside-total", "true");
    expect(tab).not.toHaveClass("sa-tq__row--child");
    for (const cell of ["orders", "ctor", "aov"]) expect(screen.getByTestId(`sa-cell-organic_shop-${cell}`)).toHaveTextContent("—");
    expect(screen.getByTestId("sa-cell-organic_shop-gmv")).not.toHaveTextContent("—");
  });

  it("Quảng cáo shows — in every cell, never 0, and no caption or ước tính appears", async () => {
    const { container } = renderWith(<TongQuanView params={params()} />, fakeApi({ split: tiktokSplit() }), { platform: "tiktok" });
    await screen.findByTestId("sa-channels");
    const ads = screen.getByTestId("sa-channel-ads");
    for (const cell of ["views", "ctr", "ctor", "aov", "gmv", "share", "orders"]) {
      expect(within(ads).getByTestId(`sa-cell-ads-${cell}`)).toHaveTextContent(/^—$/);
    }
    expect(container.textContent).not.toMatch(/ước tính/i);
  });

  it("X-1 · one number per metric: the composition and the channel table agree for the same source", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi({ split: tiktokSplit() }), { platform: "tiktok" });
    await screen.findByTestId("sa-channels");
    for (const [key, gmv] of [["organic", "3,61 tr đ"], ["affiliate", "1,20 tr đ"]] as const) {
      expect(screen.getByTestId(`sa-comp-${key}`)).toHaveTextContent(gmv);
      expect(screen.getByTestId(`sa-cell-${key}-gmv`)).toHaveTextContent(gmv);
    }
  });

  it("Shopee keeps its names and its rows in the same order", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi(), {});
    await screen.findByTestId("sa-channels");
    expect(screen.getByTestId("sa-platform")).toHaveTextContent("Shopee");
    expect(screen.getByTestId("sa-channel-organic_shop")).toHaveTextContent("Trang shop");
    expect(screen.getByTestId("sa-channel-organic_shop")).not.toHaveAttribute("data-outside-total");
    expect(screen.getByTestId("sa-channel-ads_product")).toHaveTextContent("DVHT Sản phẩm");
  });
});
