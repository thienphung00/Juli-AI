import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  PLATFORM_NAME_TABLE,
  SOURCE_LABEL_TABLE,
  channelCellBlank,
  channelLabel,
  channelName,
  channelRowsForDisplay,
  sourceFunnelName,
  sourceName,
  sourceUnavailable,
  sourcesOutsideTotal,
  streamName,
  streamShortName,
} from "../platform-labels";
import { SOURCES, SOURCE_NAME } from "../shopee-analytics/params";
import { CHANNEL_LABEL } from "../shopee-analytics/metric-view";

describe("W3 U-1 · one label table per platform", () => {
  it("Shopee spells every source as the screens it replaced did", () => {
    expect(SOURCE_NAME).toMatchObject({
      all: "Tất cả",
      the_san_pham: "Thẻ sản phẩm",
      trang_shop: "Trang shop",
      live: "Live",
      video: "Video",
      lien_ket: "Tiếp thị liên kết",
      ads: "Dịch vụ hiển thị",
    });
    expect(SOURCES.map(([key, label]) => [key, label]).slice(0, 7)).toEqual([
      ["all", "Tất cả"],
      ["the_san_pham", "Thẻ sản phẩm"],
      ["trang_shop", "Trang shop"],
      ["live", "Live"],
      ["video", "Video"],
      ["lien_ket", "Tiếp thị liên kết"],
      ["ads", "DVHT (trong đó)"],
    ]);
    expect(CHANNEL_LABEL).toEqual({
      the_san_pham: "Thẻ sản phẩm",
      trang_shop: "Trang shop",
      video: "Video",
      live: "Live",
      ads_product: "DVHT Sản phẩm",
      ads_shop: "DVHT Shop+",
      lien_ket: "Tiếp thị liên kết",
    });
    expect(sourceFunnelName("shopee", "the_san_pham_khac")).toBe("Thẻ sản phẩm (ngoài Trang shop)");
    expect(sourceFunnelName("shopee", "lien_ket")).toBe("Liên kết");
    expect(streamName("shopee", "seller_live")).toBe("Live");
    expect(streamShortName("tiktok", "shop_tab")).toBe("Tab");
  });

  it("TikTok follows decision #7: Thẻ sản phẩm, Tab cửa hàng, Video, LIVE, Tiếp thị liên kết, Quảng cáo", () => {
    expect(["the_san_pham", "trang_shop", "video", "live", "lien_ket", "ads"].map((k) => sourceName("tiktok", k))).toEqual([
      "Thẻ sản phẩm",
      "Tab cửa hàng",
      "Video",
      "LIVE",
      "Tiếp thị liên kết",
      "Quảng cáo",
    ]);
    expect(sourceName("tiktok", "the_san_pham_khac")).toBe("Thẻ sản phẩm");
    expect(streamName("tiktok", "shop_tab")).toBe("Tab cửa hàng");
    expect(PLATFORM_NAME_TABLE.tiktok).toBe("TikTok Shop");
    expect(channelName("tiktok", "organic_shop")).toBe("Tab cửa hàng");
    expect(channelName("tiktok", "ads_product")).toBe("Quảng cáo");
    expect(channelLabel("tiktok", "live")).toBe("LIVE");
  });

  it("Tab cửa hàng is outside the total and Quảng cáo is unavailable; Shopee has neither rule", () => {
    expect(sourcesOutsideTotal("tiktok")).toEqual(["trang_shop"]);
    expect(sourcesOutsideTotal("shopee")).toEqual([]);
    expect(sourceUnavailable("tiktok", "ads")).toBe(true);
    expect(sourceUnavailable("shopee", "ads")).toBe(false);
    expect(Object.keys(SOURCE_LABEL_TABLE.tiktok)).toEqual(Object.keys(SOURCE_LABEL_TABLE.shopee));
  });

  it("cells TikTok never gives are blank (—), never 0", () => {
    for (const cell of ["orders", "ctor", "aov"]) expect(channelCellBlank("tiktok", "organic_shop", cell)).toBe(true);
    expect(channelCellBlank("tiktok", "organic_shop", "gmv")).toBe(false);
    for (const cell of ["views", "gmv", "orders"]) expect(channelCellBlank("tiktok", "ads", cell)).toBe(true);
    expect(channelCellBlank("tiktok", "organic_video", "orders")).toBe(false);
    expect(channelCellBlank("shopee", "organic_shop", "orders")).toBe(false);
    expect(channelCellBlank("shopee", "ads", "gmv")).toBe(false);
  });

  it("rows outside the total go last and stand alone on TikTok; Shopee order is untouched", () => {
    const rows = [
      { key: "organic", parent: null },
      { key: "organic_card", parent: "organic" },
      { key: "organic_shop", parent: "organic" },
      { key: "organic_video", parent: "organic" },
    ];
    expect(channelRowsForDisplay("tiktok", rows).map((r) => [r.key, r.parent])).toEqual([
      ["organic", null],
      ["organic_card", "organic"],
      ["organic_video", "organic"],
      ["organic_shop", null],
    ]);
    expect(channelRowsForDisplay("shopee", rows)).toEqual(rows);
  });

  it("the scattered maps are gone: the screens read the table", () => {
    const root = join(__dirname, "..", "..");
    const read = (p: string) => readFileSync(join(root, p), "utf8");
    expect(read("components/ops/ops-simulate.tsx")).not.toContain('shop_tab: "Tab cửa hàng"');
    expect(read("components/ops/shopee/ops-shopee-products.tsx")).not.toContain("const STREAM_LABEL");
    expect(read("components/ops/ops-shop-settings.tsx")).not.toContain("const STREAM_LABEL");
    expect(read("components/shopee-decisions/option-card/option-card.tsx")).not.toContain('trang_shop: "Trang shop"');
    expect(read("components/shopee-analytics/tong-quan.tsx")).not.toContain("const NAMES");
    expect(read("lib/shopee-analytics/metric-view.ts")).not.toContain('trang_shop: "Trang shop"');
  });
});
