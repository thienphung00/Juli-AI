import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { critical, fakeApi, product } from "../../../lib/shopee-analytics/__tests__/fixtures";
import { ShopeeHostProvider, type ShopeeHost } from "../../../lib/shopee-analytics/context";
import { sellerLinks } from "../../../lib/shopee-analytics/links";
import { fakeKol, row } from "../../../lib/shopee-kol/__tests__/fixtures";
import type { KolApi, KolCompareGroup, KolCompareReport, KolCompareRow } from "../../../lib/shopee-kol/types";
import { COMPARE_HEADS, KolCompare } from "../kol-compare";
import { KolView } from "../kol-view";

/** Synthetic groups and numbers (P100 `kol_compare.compare`); no creator, shop or order data. */

function grp(over: Partial<KolCompareRow> = {}): KolCompareRow {
  return { key: "g", label: "Nhóm", orders: 12, units: 14, gmv: 1_200_000, cost: 18_000, cost_pct_gmv: 1.5, sample_cost: 0, net_profit: 240_000, profit_after_samples: 240_000, profit_orders: 12, profit_per_order: 20_000, roi_incl_samples: 13.3, kols: 3, products: 2, share_gmv_pct: 60, low_data: false, low_data_label: null, ...over };
}

const GROUP_ROWS: Record<KolCompareGroup, readonly KolCompareRow[]> = {
  channel: [grp({ key: "Trong Shopee (Video/Live)", label: "Trong Shopee (Video/Live)" }), grp({ key: "Facebook", label: "Facebook", orders: 4, gmv: 800_000, cost: 12_000, sample_cost: 50_000, net_profit: 30_000, profit_after_samples: -20_000, roi_incl_samples: -0.32, share_gmv_pct: 40, low_data: true, low_data_label: "Ít dữ liệu" })],
  campaign_type: [grp({ key: "Chiến dịch mở", label: "Chiến dịch mở", orders: 16, gmv: 2_000_000, share_gmv_pct: 100 })],
  kol: [grp({ key: "k1", label: "KOL mẫu A", kols: 1 })],
};

function compareOf(group: KolCompareGroup): KolCompareReport {
  const label = { channel: "Kênh", campaign_type: "Loại chiến dịch", kol: "KOL" }[group];
  return {
    window: { from: "2026-10-01", to: "2026-10-30", days: 30 },
    group,
    group_label: label,
    rows: GROUP_ROWS[group],
    total: grp({ key: "total", label: "Tổng Tiếp thị liên kết", orders: 16, gmv: 2_000_000, cost: 30_000 }),
    streams: {
      rows: [
        { key: "affiliate", label: "Tiếp thị liên kết", gmv: 1_500_000, orders: 15, basis: { key: "traffic_sources", label: "Theo nguồn lưu lượng" }, cost: 80_000, cost_basis: { key: "kol_conversion_report", label: "Theo báo cáo chuyển đổi KOL" }, cost_pct_gmv: 4, profit_after_cost: 220_000, profit_reason: null, reason: null, note: null, conversion_report: { gmv: 2_000_000, orders: 16 } },
        { key: "ads", label: "Quảng cáo (Dịch vụ hiển thị)", gmv: 1_200_000, orders: 12, basis: { key: "ads_report", label: "Theo báo cáo quảng cáo (đơn đã đặt)" }, cost: 300_000, cost_basis: { key: "ads_report", label: "Theo báo cáo quảng cáo (đơn đã đặt)" }, cost_pct_gmv: 25, profit_after_cost: null, profit_reason: "Juli chỉ tính lợi nhuận ở cấp shop.", reason: null, note: null },
        { key: "organic", label: "Thẻ sản phẩm + Video/Live của shop", gmv: null, orders: null, basis: { key: "traffic_sources", label: "Theo nguồn lưu lượng" }, cost: null, cost_basis: null, cost_pct_gmv: null, profit_after_cost: null, profit_reason: "Juli chỉ tính lợi nhuận ở cấp shop.", reason: "Chưa có lưu lượng theo nguồn của Seller Centre trong kỳ.", note: null },
      ],
      shop_gmv: 6_500_000,
      shop_orders: 65,
      note: "Hai cách đếm Tiếp thị liên kết khác nhau.",
    },
    basis: { key: "kol_conversion_report", label: "Theo báo cáo chuyển đổi KOL" },
    labels: { cost: "Hoa hồng Shopee thu", net_profit: "sau phí sàn, giá vốn, đóng gói và hoa hồng; trước quảng cáo", profit_per_order: "", roi_formula: "(ròng − mẫu) ÷ (hoa hồng + mẫu)", low_data: "Ít dữ liệu", low_data_threshold: 10, share_gmv: "" },
  };
}

function withCompare(): KolApi & { readonly groups: KolCompareGroup[] } {
  const groups: KolCompareGroup[] = [];
  return { ...fakeKol([row({ channel: "1", channel_label: "Trong Shopee (Video/Live)" }), row({ kol_key: "k2", channel: "Facebook", item_id: "TR-B" })]), groups, compare: async (g) => (groups.push(g), compareOf(g)) };
}

function host(kol: KolApi | undefined): ShopeeHost {
  return { api: fakeApi({ product: product(), critical: critical() }), kol, links: sellerLinks, shopKey: "shop-1", shopName: "Shop mẫu" };
}

describe("Phân tích › KOL › So sánh (P100)", () => {
  it("groups by Kênh with cost, cost %, sample, profit and ROI; the basis is named; Ít dữ liệu shows", async () => {
    render(
      <ShopeeHostProvider host={host(withCompare())}>
        <KolCompare />
      </ShopeeHostProvider>,
    );
    const table = await screen.findByTestId("kol-compare-table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Kênh", ...COMPARE_HEADS.slice(1)]);
    expect(screen.getByTestId("kol-compare-basis")).toHaveTextContent("Theo báo cáo chuyển đổi KOL");
    const fb = within(screen.getByTestId("kol-compare-row-Facebook")).getAllByRole("cell").map((c) => c.textContent);
    expect(fb[0]).toContain("Facebook");
    expect(fb[0]).toContain("Ít dữ liệu");
    expect(fb.slice(1)).toEqual(["4", "800.000đ", "12.000đ", "1,5%", "50.000đ", "30.000đ", "20.000đ", "−32%", "3", "40,0%"]);
    expect(within(screen.getByTestId("kol-compare-row-Trong Shopee (Video/Live)")).queryByText("Ít dữ liệu")).toBeNull();
    expect(within(screen.getByTestId("kol-compare-total")).getAllByRole("cell")[0]).toHaveTextContent("Tổng");
  });

  it("the stream strip puts Affiliate beside Ads and the shop's flows, each with its basis and null + reason", async () => {
    render(
      <ShopeeHostProvider host={host(withCompare())}>
        <KolCompare />
      </ShopeeHostProvider>,
    );
    const aff = await screen.findByTestId("kol-stream-affiliate");
    expect(aff).toHaveTextContent("1.500.000đ");
    expect(aff).toHaveTextContent("Theo nguồn lưu lượng");
    expect(aff).toHaveTextContent("Chi phí: Theo báo cáo chuyển đổi KOL");
    expect(aff).toHaveTextContent("Lợi nhuận sau chi phí 220.000đ");
    expect(screen.getByTestId("kol-stream-ads")).toHaveTextContent("Chi phí 300.000đ · 25,0% GMV");
    expect(screen.getByTestId("kol-stream-ads")).toHaveTextContent("Juli chỉ tính lợi nhuận ở cấp shop.");
    expect(screen.getByTestId("kol-stream-organic")).toHaveTextContent("Chưa có lưu lượng theo nguồn");
  });

  it("the toggle asks the server for another grouping", async () => {
    const kol = withCompare();
    render(
      <ShopeeHostProvider host={host(kol)}>
        <KolCompare />
      </ShopeeHostProvider>,
    );
    await screen.findByTestId("kol-compare-table");
    fireEvent.click(screen.getByRole("button", { name: "Loại chiến dịch" }));
    expect(await screen.findByTestId("kol-compare-row-Chiến dịch mở")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "KOL" }));
    await waitFor(() => expect(screen.getByTestId("kol-compare-row-k1")).toBeInTheDocument());
    expect(kol.groups).toEqual(["channel", "campaign_type", "kol"]);
  });

  it("sits in Phân tích › KOL, which labels the channel; a host without compare shows nothing", async () => {
    const first = render(
      <ShopeeHostProvider host={host(withCompare())}>
        <KolView />
      </ShopeeHostProvider>,
    );
    expect(await screen.findByTestId("kol-compare")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Trong Shopee (Video/Live)" })).toBeInTheDocument();
    expect(within(screen.getByTestId("kol-row-k1-GT-A")).getAllByRole("cell")[0]).toHaveTextContent("Trong Shopee (Video/Live)");
    first.unmount();
    render(
      <ShopeeHostProvider host={host(fakeKol())}>
        <KolView />
      </ShopeeHostProvider>,
    );
    await screen.findByTestId("kol-table");
    expect(screen.queryByTestId("kol-compare")).toBeNull();
  });
});
