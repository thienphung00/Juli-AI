import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OpsApiError } from "../../../lib/ops/api";
import { fmtSetting } from "../../../lib/ops/setting-changes";
import type { CardGroup, CardGroupsPage } from "../../../lib/ops/types";
import { auditWhat } from "../audit-text";
import { OpsCardGroups, planText } from "../ops-card-groups";

/** P36 (D45, Ops only): Ops groups, the drift floor, AOV / items per order, the CTR guard, the reason. */

const PACK: CardGroup = {
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
  members: [
    { product_id: "pk00", product_title: "Nước giặt 3,6 kg", arm: "control", card_id: null, card_status: null, surfaced_at: null, approved: false, released_at: null },
    { product_id: "pk01", product_title: "Nước xả 3,2 kg", arm: "treated", card_id: null, card_status: null, surfaced_at: null, approved: false, released_at: null },
  ],
  verdict: {
    as_of: "2026-10-29",
    window_days: 14,
    primary: { n_treated: 4, n_control: 2, label: "Đang đo", median_treated: 25, median_control: 0, difference: 25, interval: [18, 31], strength: null, strength_label: null },
    approved_only: { n_treated: 0, n_control: 2, label: "Chưa đủ cơ sở", median_treated: null, median_control: null, difference: null, interval: null, strength: null, strength_label: null },
    adjustment: { method: "one_window", theta: 0.8, theta_pre: null, two_window_min: 15 },
    metrics: {
      "items_per_order|total": {
        metric: "items_per_order",
        channel: "total",
        label: "Số món mỗi đơn · tất cả kênh",
        primary: { n_treated: 4, n_control: 2, label: "Sơ bộ", median_treated: 24, median_control: 0, difference: 24, interval: [20, 29], strength: "clear", strength_label: "Thay đổi rõ" },
      },
      "ctr|product_card": {
        metric: "ctr",
        channel: "product_card",
        label: "CTR · Thẻ sản phẩm",
        primary: { n_treated: 4, n_control: 2, label: "Sơ bộ", median_treated: -20, median_control: 0, difference: -20, interval: [-24, -15], strength: "clear", strength_label: "Thay đổi rõ" },
      },
    },
    guard: {
      metric: "ctr",
      channel: "product_card",
      max_drop_pct: 15,
      difference: -20,
      primary_difference: 25,
      warning: true,
      text: "Cảnh báo: CTR thẻ sản phẩm của nhóm áp dụng giảm 20 % so với đối chứng (ngưỡng 15 %) dù AOV tăng 25 %",
    },
    products: [],
  },
  seller_sentence: null,
  design: { source: "ops", reason: "Phương án đầu ở 25/26 sp", guard: true, created_by: "ops@app-juli.com" },
  plan: {
    weeks: 2,
    sigma_week: 0.15,
    n_treated: 4,
    n_control: 2,
    floor: { pooled_pct: 10.1, difference_pct: 21.4 },
    needed_per_arm: { unit: "orders", half_width_pct: 10, no_drift: 195, with_drift: null, reachable: false },
    have_before: {
      treated: { impressions: 280000, clicks: 11200, orders: 560, gmv: 112000000 },
      control: { impressions: 140000, clicks: 5600, orders: 280, gmv: 56000000 },
    },
    have_window: ["2026-10-02", "2026-10-15"],
  },
};

const PAGE: CardGroupsPage = { enabled: false, groups: [PACK] };

describe("Nhóm thử nghiệm tạo trong Ops (D45)", () => {
  it("shows the drift floor next to the traffic needed, AOV / items per order and the CTR guard", async () => {
    render(<OpsCardGroups load={vi.fn(async () => PAGE)} shopId="s1" />);
    const [group] = await screen.findAllByTestId("ops-group");
    expect(group).toHaveTextContent("Tạo trong Ops");
    expect(group).toHaveTextContent("đối chứng được đổi từ 30/10/2026");
    expect(within(group).getByTestId("ops-group-plan")).toHaveTextContent(
      "Sàn trôi tuần của khoảng 90 %: ±10,1 % (6 sp × 2 tuần; áp dụng − đối chứng ±21,4 %) · Cần mỗi nhánh cho ±10,0 %: 195 đơn (không tính trôi) · không đạt được khi tính trôi tuần",
    );
    expect(group).toHaveTextContent("Cách tính: điều chỉnh theo một cửa sổ tiền kỳ");
    expect(group).toHaveTextContent("Số món mỗi đơn · tất cả kênh: +24,0 điểm %");
    // The guard metric shows once, as the guard line.
    expect(group).not.toHaveTextContent("CTR · Thẻ sản phẩm: ");
    expect(within(group).getByTestId("ops-group-guard")).toHaveTextContent("dù AOV tăng 25 %");
    expect(group).toHaveTextContent("Lý do chọn thử nghiệm: Phương án đầu ở 25/26 sp");
    expect(group).toHaveTextContent("Người bán không thấy nhóm này");
    expect(group).not.toHaveTextContent("Chỉ thẻ đã duyệt");
    expect(group).not.toHaveTextContent("Người bán thấy:");
    // A viewer (canEdit false) sees no create form and no edit button.
    expect(screen.queryByRole("button", { name: "Tạo nhóm thử nghiệm" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Sửa lý do" })).toBeNull();
  });

  it("creates a pack group (4 + 2) and shows the server's refusal", async () => {
    const create = vi
      .fn()
      .mockRejectedValueOnce(new OpsApiError(422, "Đang ở một nhóm thử nghiệm khác: pk02"))
      .mockResolvedValueOnce({ ...PAGE, created: "g9" });
    render(<OpsCardGroups canEdit create={create} load={vi.fn(async () => ({ enabled: false, groups: [] }))} shopId="s1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Tạo nhóm thử nghiệm" }));
    const form = screen.getByTestId("ops-group-create");
    expect(within(form).getByRole("button", { name: /Tạo nhóm \(0 sản phẩm\)/ })).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Mã sản phẩm TikTok"), { target: { value: "pk00\npk01, pk02\npk03 pk04\npk05" } });
    fireEvent.change(within(form).getByLabelText("Lý do chọn thử nghiệm (không bắt buộc)"), { target: { value: " KG chọn " } });
    fireEvent.click(within(form).getByRole("button", { name: "Tạo nhóm (6 sản phẩm)" }));
    await screen.findByText("Đang ở một nhóm thử nghiệm khác: pk02");
    expect(create).toHaveBeenCalledWith("s1", {
      lever: "pack_option",
      metric: "aov",
      channel: "total",
      product_ids: ["pk00", "pk01", "pk02", "pk03", "pk04", "pk05"],
      reason: "KG chọn",
      guard: true,
      stratify: false,
    });
    fireEvent.click(within(form).getByRole("button", { name: "Tạo nhóm (6 sản phẩm)" }));
    await screen.findByText("AOV · Quy cách mới · tất cả kênh");
    expect(screen.queryByTestId("ops-group-create")).toBeNull();
  });

  it("shows the strata of a stratified group and a card group's Ops-only reading (D45.8, D45.6)", async () => {
    const stratified: CardGroup = {
      ...PACK,
      members: PACK.members.map((m, i) => ({ ...m, stratum: i === 0 ? "high" : "low" })),
      design: { ...PACK.design!, strata: { pk00: "high", pk01: "low" }, strata_orders: { pk00: 331, pk01: 13 } },
      verdict: {
        ...PACK.verdict!,
        ops_rule: { metric: "aov", channel: "total", label: "AOV · tất cả kênh", adjustment: { method: "two_windows", theta: 0.9, theta_pre: 0.1, two_window_min: 15 }, primary: PACK.verdict!.primary },
      },
    };
    render(<OpsCardGroups load={vi.fn(async () => ({ enabled: true, groups: [stratified] }))} shopId="s1" />);
    const [group] = await screen.findAllByTestId("ops-group");
    expect(group).toHaveTextContent("Chia tầng theo số đơn 30 ngày");
    expect(within(group).getByTestId("ops-group-ops-rule")).toHaveTextContent("Theo cách tính mới (điều chỉnh theo hai cửa sổ tiền kỳ, chỉ Ops): +25,0 điểm %");
    fireEvent.click(within(group).getByRole("button", { name: /AOV · Quy cách mới/ }));
    expect(within(group).getByText("nhiều đơn")).toBeInTheDocument();
    expect(within(group).getByText("ít đơn")).toBeInTheDocument();
  });

  it("edits the one-line reason", async () => {
    const setReason = vi.fn(async () => ({ ...PAGE, groups: [{ ...PACK, design: { ...PACK.design!, reason: "Chọn theo KG" } }] }));
    render(<OpsCardGroups canEdit load={vi.fn(async () => PAGE)} setReason={setReason} shopId="s1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Sửa lý do" }));
    fireEvent.change(screen.getByLabelText("Lý do chọn thử nghiệm"), { target: { value: "Chọn theo KG" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu lý do" }));
    await waitFor(() => expect(setReason).toHaveBeenCalledWith("s1", "g9", "Chọn theo KG"));
    await screen.findByText(/Lý do chọn thử nghiệm: Chọn theo KG/);
  });

  it("formats the plan, the tunables and the audit rows", () => {
    expect(planText(null)).toBeNull();
    expect(planText({ ...PACK.plan!, needed_per_arm: { unit: "impressions", half_width_pct: 10, no_drift: 2999, with_drift: 3930, reachable: true } })).toContain(
      "2.999 lượt hiển thị (không tính trôi) · 3.930 khi tính trôi tuần",
    );
    expect(fmtSetting("group_two_window_min", 15)).toBe("15 sản phẩm");
    expect(fmtSetting("group_guard_ctr_drop", 15)).toBe("15 %");
    expect(fmtSetting("group_drift_sigma", 0.15)).toBe("σ 0,15 / tuần");
    const row = { id: "a", at: "2026-10-16T02:00:00", actor_email: "ops@app-juli.com", shop_id: "s1", shop_name: null, merged_count: 1, kind: "config" as const };
    expect(auditWhat({ ...row, action: "card_group_create", before: null, after: { key: "aov|pack_option|total", products: ["a", "b", "c"] } })).toBe(
      "Tạo nhóm thử nghiệm aov|pack_option|total · 3 sản phẩm",
    );
    expect(auditWhat({ ...row, action: "card_group_reason", before: { reason: null }, after: { reason: "KG" } })).toBe("Lý do chọn thử nghiệm: “KG”");
  });
});
