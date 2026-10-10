import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { QdApiError } from "../../lib/quyet-dinh/api-client";
import {
  OFF_API_FIELDS,
  displayOffApiValue,
  formatLiveSlot,
  parseLiveSchedule,
} from "../../lib/quyet-dinh/off-api-rules";
import { sampleRules } from "../../lib/quyet-dinh/sample-data";
import type { ShopRules } from "../../lib/quyet-dinh/types";
import { RulesEditor } from "../quyet-dinh/rules-editor";

/**
 * P14-F (contract p14-rules-and-cost.md §3): the rule fields for what no
 * TikTok API gives Juli. Signed in they are edited like every other rule
 * (set_by, inline 422 copy, Bỏ đặt); the signed-out sample shows its sample
 * values read-only.
 */

const unset = { value: null, set_by: null, set_by_user_id: null, set_at: null };
const seller = (value: unknown) => ({ value, set_by: "seller" as const, set_by_user_id: "u1", set_at: "2026-10-10T03:00:00Z" });

function rules(over: Partial<ShopRules> = {}): ShopRules {
  return {
    stability_band: {},
    product_cost: {},
    max_discount_pct: {},
    min_margin_pct: null,
    max_open_cards: { ...unset, value: 30 },
    auto_levers: { ...unset, value: ["attributes", "description", "image", "title"] },
    protected_terms: { ...unset, value: [] },
    band_metrics: ["ctr"],
    listing_levers: ["title", "description", "attributes", "image"],
    sku_cost: {},
    default_gross_margin_pct: null,
    default_max_discount_pct: null,
    program_fee_pct: null,
    joins_platform_campaigns: null,
    platform_campaign_note: null,
    target_roas: null,
    gmv_max_daily_budget: null,
    live_schedule: null,
    weekdays: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    ...over,
  };
}

describe("LIVE slot text", () => {
  it("parses days, ranges and CN, and formats back", () => {
    expect(parseLiveSchedule("T2, T4 T6 20:00-22:00\n\n t7-cn 9:30–11:00 ")).toEqual([
      { days: ["mon", "wed", "fri"], start: "20:00", end: "22:00" },
      { days: ["sat", "sun"], start: "09:30", end: "11:00" },
    ]);
    expect(formatLiveSlot({ days: ["sat", "sun"], start: "21:00", end: "23:00" })).toBe("T7 CN 21:00-23:00");
  });

  it.each(["T2 20:00", "20:00-22:00", "T9 20:00-22:00", "T2 25:00-22:00", "T6-T2 20:00-22:00"])(
    "refuses %s with a Vietnamese message",
    (line) => {
      expect(() => parseLiveSchedule(line)).toThrow(/^vi:/);
    },
  );
});

describe("P14-F rule fields, signed in", () => {
  it("shows every field with its help, unset by default", () => {
    render(<RulesEditor onDelete={vi.fn()} onSave={vi.fn()} rules={rules()} />);
    const group = screen.getByTestId("rules-off-api");
    expect(within(group).getByText("Thông tin TikTok không cung cấp")).toBeInTheDocument();
    for (const field of OFF_API_FIELDS) {
      const row = within(group).getByTestId(`rule-${field.key}`);
      expect(row).toHaveTextContent(field.label);
      expect(row).toHaveTextContent(field.help);
    }
    expect(within(group).getByTestId("rule-target_roas")).toHaveTextContent("Mặc định");
  });

  it("saves numbers, the campaign choice, the note and LIVE slots with set_by", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<RulesEditor onDelete={vi.fn()} onSave={onSave} rules={rules()} />);

    const margin = screen.getByTestId("rule-default_gross_margin_pct");
    await userEvent.type(within(margin).getByRole("textbox"), "35,5");
    await userEvent.click(within(margin).getByRole("button", { name: "Lưu" }));
    expect(onSave).toHaveBeenLastCalledWith("default_gross_margin_pct", 35.5, "seller", null);

    const sku = screen.getByTestId("rule-sku_cost");
    await userEvent.type(within(sku).getByLabelText("Mã SKU TikTok"), "1729700293904534135");
    await userEvent.type(within(sku).getByLabelText("Giá trị (₫/sản phẩm)"), "85000");
    await userEvent.click(within(sku).getByRole("button", { name: "Thêm" }));
    expect(onSave).toHaveBeenLastCalledWith("sku_cost", 85000, "seller", "1729700293904534135");

    await userEvent.click(screen.getByRole("checkbox", { name: "Điền thay Seller (đội ngũ Juli)" }));
    const campaigns = screen.getByTestId("rule-joins_platform_campaigns");
    await userEvent.selectOptions(within(campaigns).getByRole("combobox"), "yes");
    await userEvent.click(within(campaigns).getByRole("button", { name: "Lưu" }));
    expect(onSave).toHaveBeenLastCalledWith("joins_platform_campaigns", true, "team", null);

    const note = screen.getByTestId("rule-platform_campaign_note");
    await userEvent.type(within(note).getByRole("textbox"), "  11.11 giảm 15 %  ");
    await userEvent.click(within(note).getByRole("button", { name: "Lưu" }));
    expect(onSave).toHaveBeenLastCalledWith("platform_campaign_note", "11.11 giảm 15 %", "team", null);

    const live = screen.getByTestId("rule-live_schedule");
    await userEvent.type(within(live).getByRole("textbox"), "T3 T5 20:00-22:00");
    await userEvent.click(within(live).getByRole("button", { name: "Lưu" }));
    expect(onSave).toHaveBeenLastCalledWith(
      "live_schedule",
      [{ days: ["tue", "thu"], start: "20:00", end: "22:00" }],
      "team",
      null,
    );
  });

  it("shows input mistakes and 422s inline in Vietnamese, without saving", async () => {
    const onSave = vi.fn().mockRejectedValueOnce(new QdApiError(422, null, "target_roas: value must be > 0"));
    render(<RulesEditor onDelete={vi.fn()} onSave={onSave} rules={rules()} />);

    const roas = screen.getByTestId("rule-target_roas");
    await userEvent.type(within(roas).getByRole("textbox"), "0");
    await userEvent.click(within(roas).getByRole("button", { name: "Lưu" }));
    expect(await within(roas).findByRole("alert")).toHaveTextContent("ROAS phải lớn hơn 0 và không quá 100.");

    const campaigns = screen.getByTestId("rule-joins_platform_campaigns");
    await userEvent.click(within(campaigns).getByRole("button", { name: "Lưu" }));
    expect(await within(campaigns).findByRole("alert")).toHaveTextContent("Chọn Có hoặc Không.");

    const live = screen.getByTestId("rule-live_schedule");
    await userEvent.type(within(live).getByRole("textbox"), "Thứ hai 20:00-22:00");
    await userEvent.click(within(live).getByRole("button", { name: "Lưu" }));
    expect(await within(live).findByRole("alert")).toHaveTextContent("Không hiểu ngày");
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("shows set values with who set them, and Bỏ đặt unsets", async () => {
    const onDelete = vi.fn().mockResolvedValue(undefined);
    render(
      <RulesEditor
        onDelete={onDelete}
        onSave={vi.fn()}
        rules={rules({
          joins_platform_campaigns: seller(false),
          live_schedule: seller([{ days: ["sat", "sun"], start: "21:00", end: "23:00" }]),
        })}
      />,
    );
    const live = screen.getByTestId("rule-live_schedule");
    expect(within(live).getByRole("textbox")).toHaveValue("T7 CN 21:00-23:00");
    expect(live).toHaveTextContent("Bạn đặt · 10/10/2026");
    const campaigns = screen.getByTestId("rule-joins_platform_campaigns");
    expect(within(campaigns).getByRole("combobox")).toHaveValue("no");
    await userEvent.click(within(campaigns).getByRole("button", { name: "Bỏ đặt" }));
    expect(onDelete).toHaveBeenLastCalledWith("joins_platform_campaigns", null);
  });

  it("an older backend without the P14 fields still renders them as unset", () => {
    const legacy = { ...rules() } as Record<string, unknown>;
    for (const field of OFF_API_FIELDS) delete legacy[field.key];
    render(<RulesEditor onDelete={vi.fn()} onSave={vi.fn()} rules={legacy as unknown as ShopRules} />);
    expect(screen.getByTestId("rule-sku_cost")).toHaveTextContent("Chưa đặt.");
  });
});

describe("P14-F rule fields, signed-out sample", () => {
  it("shows the sample values read-only, with no input or save button", () => {
    const sample = sampleRules();
    render(<RulesEditor offApiReadOnly onDelete={vi.fn()} onSave={vi.fn()} rules={sample} />);
    const group = screen.getByTestId("rules-off-api");
    expect(within(group).getByTestId("off-api-sample-note")).toHaveTextContent("Đăng nhập để đặt");
    expect(within(group).queryByRole("textbox")).toBeNull();
    expect(within(group).queryByRole("combobox")).toBeNull();
    expect(within(group).queryByRole("button")).toBeNull();
    expect(within(group).getByTestId("rule-target_roas")).toHaveTextContent("6 lần");
    expect(within(group).getByTestId("rule-joins_platform_campaigns")).toHaveTextContent("Có");
    expect(within(group).getByTestId("rule-live_schedule")).toHaveTextContent("T3 T5 20:00-22:00");
    expect(within(group).getByTestId("rule-gmv_max_daily_budget")).toHaveTextContent("500.000 ₫/ngày");
    expect(within(group).getByTestId("rule-sku_cost")).toHaveTextContent("SKU 1729700293904534135: 120.000 ₫");
    // The other groups stay as they were.
    expect(screen.getByTestId("rule-max_open_cards")).toBeInTheDocument();
  });

  it("formats unset values as a dash", () => {
    const empty = rules();
    for (const field of OFF_API_FIELDS) expect(displayOffApiValue(field.key, empty)).toBe("—");
  });
});
