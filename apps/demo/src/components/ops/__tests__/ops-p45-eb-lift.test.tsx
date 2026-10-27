import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { fmtSetting, SETTING_LABELS } from "../../../lib/ops/setting-changes";
import type { CardGroup, CardGroupComparison, CardGroupEb, CardGroupsPage } from "../../../lib/ops/types";
import { EB_TOOLTIP, ebText, OpsCardGroups, OWN_DATA_PRIOR } from "../ops-card-groups";

/** P45 (D52, Ops only): the EB-shrunk lift beside the raw lift; the seller sentence is unchanged. */

const POOLED: CardGroupEb = {
  observed_log_lift: 0.3365,
  se: 0.12,
  observed_pct: 40,
  weight: 0.1,
  shrunk_log_lift: 0.0305,
  shrunk_pct: 3.1,
  interval_pct: [-2, 8.4],
  prior: { source: "pooled", mean: 0.03, tau: 0.04, n_groups: 3 },
};
const DEFAULT: CardGroupEb = { ...POOLED, shrunk_pct: 20.2, interval_pct: [4.5, 38.1], prior: { source: "default", mean: 0, tau: 0.15, n_groups: 0 } };

const primary = (eb: CardGroupEb | null | undefined): CardGroupComparison => ({
  n_treated: 12,
  n_control: 3,
  label: "Sơ bộ",
  median_treated: 40,
  median_control: 0,
  difference: 40,
  interval: [20, 60],
  strength: "clear",
  strength_label: "Thay đổi rõ",
  eb,
});

const GROUP: CardGroup = {
  id: "g1",
  key: "ctr|cover_image|total",
  label: "CTR · Ảnh bìa · tất cả kênh",
  metric: "ctr",
  lever: "cover_image",
  channel: "total",
  launched_on: "2026-09-20",
  release_on: "2026-10-04",
  seed: 7,
  status: "measured",
  treated: 12,
  control: 3,
  members: [],
  verdict: {
    as_of: "2026-10-04",
    window_days: 14,
    primary: primary(POOLED),
    approved_only: { ...primary(null), label: "Chưa đủ cơ sở", difference: null, interval: null },
    metrics: {
      "aov|total": { metric: "aov", channel: "total", label: "AOV · tất cả kênh", primary: primary(DEFAULT) },
    },
    products: [],
  },
  seller_sentence: "Nhóm 15 sản phẩm đổi ảnh bìa: lượt nhấp tăng khoảng 40 % so với các sản phẩm chưa đổi (sơ bộ)",
};

describe("Lift đã co (EB) trong Ops (D52)", () => {
  it("shows the shrunk lift beside the raw one, with its prior and a plain tooltip", async () => {
    const page: CardGroupsPage = { enabled: true, groups: [GROUP] };
    render(<OpsCardGroups load={vi.fn(async () => page)} shopId="s1" />);
    const [group] = await screen.findAllByTestId("ops-group");
    const [main, aov] = within(group).getAllByTestId("ops-group-eb");
    expect(main).toHaveTextContent("Lift đã co (EB): +3,1 % [-2,0; +8,4] · lift thô +40,0 % · theo 3 nhóm cùng loại");
    expect(main).toHaveAttribute("title", EB_TOOLTIP);
    expect(EB_TOOLTIP).toBe("Điều chỉnh theo các nhóm cùng loại để tránh tin nhầm kết quả may mắn");
    expect(aov).toHaveTextContent("+20,2 % [+4,5; +38,1] · lift thô +40,0 % · mức mặc định (chưa đủ nhóm cùng loại)");
    // The raw result and the seller's sentence are unchanged.
    expect(group).toHaveTextContent("Kết quả ngày 14: +40,0 điểm % (khoảng +20,0 → +60,0) · Thay đổi rõ · Sơ bộ");
    expect(group).toHaveTextContent("Người bán thấy: “Nhóm 15 sản phẩm đổi ảnh bìa: lượt nhấp tăng khoảng 40 % so với các sản phẩm chưa đổi (sơ bộ)”");
    expect(group.textContent ?? "").not.toMatch(/Người bán thấy:[^”]*EB/);
  });

  it("shows nothing for a comparison without numbers or stored before P45", async () => {
    const old: CardGroup = { ...GROUP, verdict: { ...GROUP.verdict!, primary: primary(undefined), metrics: {} } };
    render(<OpsCardGroups load={vi.fn(async () => ({ enabled: true, groups: [old] }))} shopId="s1" />);
    const [group] = await screen.findAllByTestId("ops-group");
    expect(within(group).queryByTestId("ops-group-eb")).toBeNull();
    expect(ebText(null)).toBeNull();
    expect(ebText(undefined)).toBeNull();
  });

  it("says a shop without the pooling opt-in is estimated on its own data only (D76 / D11)", () => {
    const own: CardGroupEb = { ...DEFAULT, prior: { ...DEFAULT.prior, source: "own" } };
    expect(ebText(own)).toBe(`Lift đã co (EB): +20,2 % [+4,5; +38,1] · lift thô +40,0 % · ${OWN_DATA_PRIOR}`);
    expect(ebText(own)).not.toContain("nhóm cùng loại");
  });

  it("names the wider metric × channel cell when the lever type had too few shops (D14)", () => {
    const wide: CardGroupEb = { ...POOLED, prior: { ...POOLED.prior, n_groups: 6, cell: "metric_channel" } };
    expect(ebText(wide)).toBe("Lift đã co (EB): +3,1 % [-2,0; +8,4] · lift thô +40,0 % · theo 6 shop, mọi loại thay đổi cùng chỉ số");
    expect(ebText({ ...POOLED, prior: { ...POOLED.prior, cell: "lever_type" } })).toContain("theo 3 nhóm cùng loại");
  });

  it("formats the two EB tunables", () => {
    expect(fmtSetting("group_eb_prior_sd", 0.15)).toBe("σ 0,15");
    expect(fmtSetting("group_eb_min_groups", 3)).toBe("3 nhóm");
    expect(SETTING_LABELS.group_eb_prior_sd).toContain("EB");
  });
});
