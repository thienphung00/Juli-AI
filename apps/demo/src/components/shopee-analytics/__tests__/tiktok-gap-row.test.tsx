import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { channelRowsForDisplay } from "../../../lib/platform-labels";
import { channelSplit, fakeApi, metricView } from "../../../lib/shopee-analytics/__tests__/fixtures";
import type { ChannelRow, ChannelSplit, MetricViewRow } from "../../../lib/shopee-analytics/types";
import { PhanTichPageView } from "../phan-tich-view";
import { TongQuanView } from "../tong-quan";
import { params, renderWith } from "./harness";

/** W3.1 Q2/Q3: a TikTok source without a stored breakdown is "—" (never 0); the gap row holds the day. */

const blank = { views: null, clicks: null, ctr: null, ctor: null, aov: null, gmv: null, orders: null, share: null, prev: null };
const SOURCES = ["organic", "organic_card", "organic_shop", "organic_video", "organic_live", "affiliate"] as const;
const gapRow = (gmv: number, orders: number | null = null): ChannelRow => ({ key: "chenh_lech_nguon", parent: null, ...blank, gmv, orders, ad_base: null });

function tiktokSplit(mode: "none" | "mixed" | "full"): ChannelSplit {
  const base = channelSplit();
  const rows: ChannelRow[] = base.rows
    .filter((r) => r.key !== "ads_product" && r.key !== "ads_shop")
    .map((r) => {
      if (r.key === "ads") return { ...r, ...blank, ad_base: null };
      if (mode === "none" && (SOURCES as readonly string[]).includes(r.key)) return { ...r, ...blank };
      return r;
    });
  if (mode === "none") rows.push(gapRow(12_890_000));
  if (mode === "mixed") rows.push(gapRow(1_500_000));
  return { ...base, rows };
}

const cells = ["views", "ctr", "ctor", "aov", "gmv", "share", "orders"];

describe("TikTok Tổng quan · Chênh lệch nguồn row", () => {
  it("no day has a breakdown: every source is — and the gap row holds the whole total", async () => {
    const { container } = renderWith(<TongQuanView params={params()} />, fakeApi({ split: tiktokSplit("none") }), { platform: "tiktok" });
    await screen.findByTestId("sa-channels");
    for (const key of ["organic", "organic_card", "organic_video", "organic_live", "affiliate"]) {
      for (const cell of cells) expect(screen.getByTestId(`sa-cell-${key}-${cell}`)).toHaveTextContent(/^—$/);
    }
    const gap = screen.getByTestId("sa-channel-chenh_lech_nguon");
    expect(gap).toHaveTextContent("Chênh lệch nguồn");
    expect(screen.getByTestId("sa-cell-chenh_lech_nguon-gmv")).toHaveTextContent("12,89 tr đ");
    expect(screen.getByTestId("sa-cell-chenh_lech_nguon-gmv")).not.toHaveTextContent("—");
    for (const cell of ["views", "ctr", "ctor", "aov"]) expect(screen.getByTestId(`sa-cell-chenh_lech_nguon-${cell}`)).toHaveTextContent(/^—$/);
    const keys = screen.getAllByTestId(/^sa-channel-/).map((el) => el.getAttribute("data-testid")?.replace("sa-channel-", ""));
    expect(keys[keys.length - 1]).toBe("chenh_lech_nguon");
    expect(screen.queryByTestId("sa-composition")).toBeNull();
    expect(screen.getByTestId("sa-channels").textContent).not.toMatch(/(^|[^\d.,])0\s?(₫|đ|tr)/);
    expect(container.textContent).not.toMatch(/ước tính/);
  });

  it("mixed window: sources keep their sums over the days with a breakdown, the rest sits in the gap row", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi({ split: tiktokSplit("mixed") }), { platform: "tiktok" });
    await screen.findByTestId("sa-channels");
    expect(screen.getByTestId("sa-cell-organic-gmv")).toHaveTextContent("3,61 tr đ");
    expect(screen.getByTestId("sa-cell-affiliate-gmv")).toHaveTextContent("1,20 tr đ");
    expect(screen.getByTestId("sa-cell-chenh_lech_nguon-gmv")).toHaveTextContent("1,50 tr đ");
    expect(screen.getByTestId("sa-channel-chenh_lech_nguon")).toHaveTextContent("Chênh lệch nguồn");
  });

  it("full breakdown: no gap row and nothing extra on the page", async () => {
    const { container } = renderWith(<TongQuanView params={params()} />, fakeApi({ split: tiktokSplit("full") }), { platform: "tiktok" });
    await screen.findByTestId("sa-channels");
    expect(screen.queryByTestId("sa-channel-chenh_lech_nguon")).toBeNull();
    expect(container.textContent).not.toContain("Chênh lệch nguồn");
  });

  it("channelRowsForDisplay closes the table with the gap row, after the rows outside the total", () => {
    const rows = channelRowsForDisplay("tiktok", [gapRow(1), ...tiktokSplit("full").rows]);
    expect(rows.map((r) => r.key).slice(-2)).toEqual(["organic_shop", "chenh_lech_nguon"]);
  });
});

describe("TikTok Phân tích · Chênh lệch nguồn row", () => {
  const mrow = (key: string, p: Partial<MetricViewRow> = {}): MetricViewRow => ({ key, now: null, prev: null, change: null, impact: null, cards: 0, ...p });

  it("labels the gap row and shows a null source as —", async () => {
    const view = metricView({
      metric: "gmv",
      channels: [mrow("the_san_pham"), mrow("chenh_lech_nguon", { now: 12_890_000, prev: 10_000_000 })],
    });
    const { container } = renderWith(<PhanTichPageView params={params("metric=gmv")} />, fakeApi({ metricView: view }), { platform: "tiktok" });
    await screen.findByTestId("pt-channels");
    expect(screen.getByTestId("pt-channel-chenh_lech_nguon")).toHaveTextContent("Chênh lệch nguồn");
    expect(screen.getByTestId("pt-channel-chenh_lech_nguon")).not.toHaveTextContent("chenh_lech_nguon");
    expect(screen.getByTestId("pt-channel-the_san_pham")).toHaveTextContent("—");
    expect(screen.getByTestId("pt-channel-the_san_pham")).not.toHaveTextContent(/0\s?(₫|đ)/);
    expect(container.textContent).not.toMatch(/ước tính/);
  });

  it("full breakdown: no gap row", async () => {
    renderWith(<PhanTichPageView params={params("metric=gmv")} />, fakeApi({ metricView: metricView({ metric: "gmv" }) }), { platform: "tiktok" });
    await screen.findByTestId("pt-channels");
    expect(screen.queryByTestId("pt-channel-chenh_lech_nguon")).toBeNull();
  });
});
