import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CardGroup, CardGroupComparison, CardGroupPlan } from "../../../lib/ops/types";
import { GMV_GROSS_LABEL, GMV_GROSS_ONLY_LABEL, OpsCardGroups, REVENUE_NET_LABEL, revenueText } from "../ops-card-groups";

/** P46 (D55.1, Ops only): AOV / items per order net of cancelled / refunded orders, TikTok GMV beside it. */

const cmp = (difference: number): CardGroupComparison => ({
  n_treated: 4,
  n_control: 2,
  label: "Sơ bộ",
  median_treated: difference,
  median_control: 0,
  difference,
  interval: [difference - 5, difference + 5],
  strength: "clear",
  strength_label: "Thay đổi rõ",
});

const PLAN: CardGroupPlan = {
  weeks: 2,
  sigma_week: 0.15,
  n_treated: 4,
  n_control: 2,
  floor: { pooled_pct: 10.1, difference_pct: 21.4 },
  needed_per_arm: null,
  have_before: {
    treated: { impressions: 1, clicks: 1, orders: 560, gmv: 112_000_000, orders_net: 530, gmv_net: 101_500_000 },
    control: { impressions: 1, clicks: 1, orders: 280, gmv: 56_000_000, orders_net: 270, gmv_net: 52_300_000 },
  },
  have_window: ["2026-10-02", "2026-10-15"],
  revenue_basis: "net",
};

const BASE: CardGroup = {
  id: "g9",
  key: "aov|pack_option|total",
  label: "AOV · Quy cách mới · tất cả kênh",
  metric: "aov",
  lever: "pack_option",
  channel: "total",
  launched_on: "2026-10-16",
  release_on: "2026-10-30",
  seed: 777,
  status: "measured",
  treated: 4,
  control: 2,
  members: [],
  verdict: {
    as_of: "2026-10-29",
    window_days: 14,
    primary: cmp(-37.5),
    approved_only: cmp(0),
    basis: { money: "net", text: "AOV và số món mỗi đơn tính trên doanh thu đã trừ đơn huỷ/hoàn (theo đơn hàng của shop); số theo GMV TikTok (gồm huỷ/hoàn) ghi bên cạnh" },
    gross: { metric: "aov", channel: "total", label: "AOV (gồm đơn huỷ/hoàn, theo TikTok) · tất cả kênh", basis: "gross", primary: cmp(25) },
    metrics: {
      "items_per_order|total": {
        metric: "items_per_order",
        channel: "total",
        label: "Số món mỗi đơn (đã trừ huỷ/hoàn) · tất cả kênh",
        basis: "net",
        primary: cmp(-37.5),
        gross: { metric: "items_per_order", channel: "total", label: "Số món mỗi đơn (gồm đơn huỷ/hoàn, theo TikTok) · tất cả kênh", basis: "gross", primary: cmp(24) },
      },
    },
    products: [],
  },
  seller_sentence: null,
  design: { source: "ops", reason: null, guard: true, created_by: "ops@app-juli.com" },
  plan: PLAN,
};

describe("Nhóm thử nghiệm: GMV trừ huỷ/hoàn (D55.1)", () => {
  it("shows the net reading with the TikTok GMV reading beside it", async () => {
    render(<OpsCardGroups load={vi.fn(async () => ({ enabled: false, groups: [BASE] }))} shopId="s1" />);
    const [group] = await screen.findAllByTestId("ops-group");
    expect(group).toHaveTextContent("Kết quả ngày 14: -37,5 điểm %");
    expect(within(group).getByTestId("ops-group-basis")).toHaveTextContent("đã trừ đơn huỷ/hoàn");
    expect(within(group).getByTestId("ops-group-gross")).toHaveTextContent("AOV (gồm đơn huỷ/hoàn, theo TikTok) · tất cả kênh: +25,0 điểm %");
    expect(group).toHaveTextContent("Số món mỗi đơn (đã trừ huỷ/hoàn) · tất cả kênh: -37,5 điểm %");
    expect(within(group).getByTestId("ops-group-metric-gross")).toHaveTextContent("Số món mỗi đơn (gồm đơn huỷ/hoàn, theo TikTok) · tất cả kênh: +24,0 điểm %");
    expect(within(group).getByTestId("ops-group-revenue")).toHaveTextContent(
      "14 ngày trước khi bắt đầu · Doanh thu (đã trừ huỷ/hoàn): 101,5 tr áp dụng · 52,3 tr đối chứng · GMV TikTok (gồm huỷ/hoàn): 112,0 tr áp dụng · 56,0 tr đối chứng",
    );
  });

  it("shows a card group's net reading as Ops-only and keeps the seller's sentence", async () => {
    const card: CardGroup = {
      ...BASE,
      key: "aov|buy_more_save_more|total",
      lever: "buy_more_save_more",
      design: { source: "cards", reason: null, guard: true, created_by: null },
      seller_sentence: "Nhóm 6 sản phẩm thêm mua nhiều giảm nhiều: giá trị mỗi đơn tăng khoảng 25 % so với các sản phẩm chưa đổi (sơ bộ)",
      verdict: {
        ...BASE.verdict!,
        primary: cmp(25),
        gross: undefined,
        net: { metric: "aov", channel: "total", label: "AOV (đã trừ huỷ/hoàn) · tất cả kênh", basis: "net", primary: cmp(-37.5) },
      },
    };
    render(<OpsCardGroups load={vi.fn(async () => ({ enabled: true, groups: [card] }))} shopId="s1" />);
    const [group] = await screen.findAllByTestId("ops-group");
    expect(group).toHaveTextContent("Kết quả ngày 14: +25,0 điểm %");
    expect(within(group).getByTestId("ops-group-net")).toHaveTextContent("AOV (đã trừ huỷ/hoàn) · tất cả kênh (chỉ Ops): -37,5 điểm %");
    expect(group).toHaveTextContent("Người bán thấy: “Nhóm 6 sản phẩm thêm mua nhiều giảm nhiều: giá trị mỗi đơn tăng khoảng 25 %");
    expect(within(group).queryByTestId("ops-group-gross")).toBeNull();
  });

  it("labels TikTok GMV alone when the shop's orders do not cover the window", () => {
    const gross: CardGroupPlan = {
      ...PLAN,
      revenue_basis: "gross",
      have_before: {
        treated: { impressions: 1, clicks: 1, orders: 560, gmv: 112_000_000 },
        control: { impressions: 1, clicks: 1, orders: 280, gmv: 56_000_000 },
      },
    };
    expect(revenueText(gross)).toBe("14 ngày trước khi bắt đầu · GMV (gồm đơn huỷ/hoàn, theo TikTok): 112,0 tr áp dụng · 56,0 tr đối chứng");
    // A plan stored before P46 (no revenue_basis) reads the same way.
    expect(revenueText({ ...gross, revenue_basis: undefined })).toContain(GMV_GROSS_ONLY_LABEL);
    expect(revenueText(PLAN)).toContain(REVENUE_NET_LABEL);
    expect(revenueText(PLAN)).toContain(GMV_GROSS_LABEL);
    expect(revenueText(null)).toBeNull();
  });
});
