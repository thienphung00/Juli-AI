import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { describeSettingsAudit, fmtSetting } from "../../../lib/ops/setting-changes";
import type { OpsMe, ShopSettingsPage } from "../../../lib/ops/types";
import { OpsShopSettings } from "../ops-shop-settings";
import { ME, SETTINGS, SHOP_ID } from "./fixtures";

/** P23 (D29.11): "Chẩn đoán & KPI" tunables in Cài đặt shop, through the D27 draft + confirm. */

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), usePathname: () => "/ops" }));

beforeEach(() => {
  window.localStorage.clear();
});

function api(page: ShopSettingsPage = SETTINGS) {
  return {
    settings: vi.fn(async () => page),
    putSettings: vi.fn(async () => ({ settings: page.settings })),
    resetSettings: vi.fn(async () => ({ settings: page.settings })),
    invite: vi.fn(async () => ({ data: {} as never, email_sent: true, accept_url: null })),
  };
}

async function open(a = api(), me: OpsMe = ME) {
  render(<OpsShopSettings api={a} me={me} shopId={SHOP_ID} />);
  await screen.findByRole("heading", { name: "Mỹ phẩm Thảo Nhi · Cài đặt shop" });
  return a;
}

function section() {
  return screen.getByTestId("ops-diag");
}

describe("Chẩn đoán & KPI (D29.11)", () => {
  it("is collapsed; opened it lists the eight tunables at their defaults", async () => {
    await open();
    const toggle = within(section()).getByRole("button", { name: /Chẩn đoán & KPI/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(within(section()).queryAllByTestId("ops-setting")).toHaveLength(0);
    fireEvent.click(toggle);
    const rows = within(section()).getAllByTestId("ops-setting");
    expect(rows).toHaveLength(8);
    expect(rows.map((r) => within(r).getByRole("button", { name: /^Sửa / }).textContent)).toEqual([
      "14 · 30 · 60 ngày",
      "30 lượt nhấp/đơn",
      "×1 dao động",
      "×3 dao động",
      "×1 dao động",
      "CV > 30 %",
      "Một chỉ số giảm",
      "Bật (kéo về mức của ngành hàng)",
    ]);
    for (const row of rows) expect(row).toHaveTextContent("Mặc định");
  });

  it("P30 (D39.1): the card trigger rolls back to GMV giảm (cũ) through the draft", async () => {
    const a = await open();
    fireEvent.click(within(section()).getByRole("button", { name: /Chẩn đoán & KPI/ }));
    fireEvent.click(screen.getByRole("button", { name: "Sửa Điều kiện mở thẻ" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Điều kiện mở thẻ" }), { target: { value: "gmv_first" } });
    const bar = screen.getByRole("region", { name: "Thay đổi chưa lưu" });
    fireEvent.click(within(bar).getByRole("button", { name: "Lưu thay đổi (1)" }));
    const dialog = screen.getByRole("dialog", { name: "Lưu 1 thay đổi cho Mỹ phẩm Thảo Nhi?" });
    expect(within(dialog).getAllByTestId("confirm-row").map((r) => r.textContent)).toEqual([
      "Điều kiện mở thẻMột chỉ số giảm → GMV giảm (cũ)",
    ]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Xác nhận lưu" }));
    await waitFor(() => expect(a.putSettings).toHaveBeenCalledWith(SHOP_ID, { diag_trigger: "gmv_first" }));
  });

  it("P31 (D41.2): CTR / CTOR shrinkage switches off through the draft", async () => {
    const a = await open();
    fireEvent.click(within(section()).getByRole("button", { name: /Chẩn đoán & KPI/ }));
    fireEvent.click(screen.getByRole("button", { name: "Sửa Lọc nhiễu CTR / CTOR" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Lọc nhiễu CTR / CTOR" }), { target: { value: "off" } });
    const bar = screen.getByRole("region", { name: "Thay đổi chưa lưu" });
    fireEvent.click(within(bar).getByRole("button", { name: "Lưu thay đổi (1)" }));
    const dialog = screen.getByRole("dialog", { name: "Lưu 1 thay đổi cho Mỹ phẩm Thảo Nhi?" });
    expect(within(dialog).getAllByTestId("confirm-row").map((r) => r.textContent)).toEqual([
      "Lọc nhiễu CTR / CTORBật (kéo về mức của ngành hàng) → Tắt (so số thô)",
    ]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Xác nhận lưu" }));
    await waitFor(() => expect(a.putSettings).toHaveBeenCalledWith(SHOP_ID, { kpi_shrinkage: "off" }));
  });

  it("changes are a draft; Lưu confirms each before → after and sends ONE PUT", async () => {
    const a = await open();
    fireEvent.click(within(section()).getByRole("button", { name: /Chẩn đoán & KPI/ }));
    fireEvent.click(screen.getByRole("button", { name: "Sửa Cửa sổ chẩn đoán" }));
    fireEvent.click(screen.getByRole("button", { name: "60 ngày", pressed: true }));
    fireEvent.click(screen.getByRole("button", { name: "Sửa KPI tối đa" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "KPI tối đa" }), { target: { value: "2.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Sửa Ngưỡng lưu lượng ổn định" }));
    const cv = screen.getByRole("spinbutton", { name: "Ngưỡng lưu lượng ổn định" });
    expect(cv).toHaveValue(30);
    fireEvent.change(cv, { target: { value: "25" } });
    const bar = screen.getByRole("region", { name: "Thay đổi chưa lưu" });
    expect(bar).toHaveTextContent("3 thay đổi chưa lưu");
    expect(within(section()).getByRole("button", { name: /Chẩn đoán & KPI/ })).toHaveTextContent("3 ghi đè");
    expect(a.putSettings).not.toHaveBeenCalled();
    fireEvent.click(within(bar).getByRole("button", { name: "Lưu thay đổi (3)" }));
    const dialog = screen.getByRole("dialog", { name: "Lưu 3 thay đổi cho Mỹ phẩm Thảo Nhi?" });
    expect(within(dialog).getAllByTestId("confirm-row").map((r) => r.textContent)).toEqual([
      "Cửa sổ chẩn đoán14 · 30 · 60 ngày → 14 · 30 ngày",
      "KPI tối đa×3 dao động → ×2,5 dao động",
      "Ngưỡng lưu lượng ổn địnhCV > 30 % → CV > 25 %",
    ]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Xác nhận lưu" }));
    await waitFor(() => expect(a.putSettings).toHaveBeenCalledTimes(1));
    expect(a.putSettings).toHaveBeenCalledWith(SHOP_ID, { diag_windows: [14, 30], kpi_max_band_mult: 2.5, volatile_cv: 0.25 });
  });

  it("the last window cannot be switched off; invalid numbers are not drafted", async () => {
    await open();
    fireEvent.click(within(section()).getByRole("button", { name: /Chẩn đoán & KPI/ }));
    fireEvent.click(screen.getByRole("button", { name: "Sửa Cửa sổ chẩn đoán" }));
    fireEvent.click(screen.getByRole("button", { name: "14 ngày", pressed: true }));
    fireEvent.click(screen.getByRole("button", { name: "30 ngày", pressed: true }));
    fireEvent.click(screen.getByRole("button", { name: "60 ngày", pressed: true }));
    expect(screen.getByRole("button", { name: "60 ngày", pressed: true })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sửa Dữ liệu tối thiểu" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Dữ liệu tối thiểu" }), { target: { value: "0" } });
    expect(screen.getByRole("region", { name: "Thay đổi chưa lưu" })).toHaveTextContent("1 thay đổi chưa lưu");
  });

  it("an override reads Ghi đè with về mặc định (a draft back to null)", async () => {
    const page: ShopSettingsPage = {
      ...SETTINGS,
      settings: { ...SETTINGS.settings, overrides: { ...SETTINGS.settings.overrides, openai_monthly_cap_usd: null, guard_band_mult: 1.5 } },
    };
    const a = await open(api(page));
    fireEvent.click(within(section()).getByRole("button", { name: /Chẩn đoán & KPI/ }));
    const row = within(section()).getAllByTestId("ops-setting")[4];
    expect(row).toHaveTextContent("Ghi đè");
    expect(row).toHaveTextContent("×1,5 dao động");
    fireEvent.click(within(row).getByRole("button", { name: "về mặc định" }));
    fireEvent.click(screen.getByRole("button", { name: "Lưu thay đổi (1)" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Xác nhận lưu" }));
    await waitFor(() => expect(a.putSettings).toHaveBeenCalledWith(SHOP_ID, { guard_band_mult: null }));
  });

  it("a viewer cannot open the rows for editing", async () => {
    await open(api(), { ...ME, role: "viewer" as const, role_label: "Xem" });
    fireEvent.click(within(section()).getByRole("button", { name: /Chẩn đoán & KPI/ }));
    for (const b of within(section()).getAllByRole("button", { name: /^Sửa / })) expect(b).toBeDisabled();
  });

  it("an older backend without the keys shows no section", async () => {
    const defaults: Record<string, unknown> = { ...SETTINGS.settings.defaults };
    for (const k of ["diag_windows", "diag_min_events", "kpi_min_band_mult", "kpi_max_band_mult", "guard_band_mult", "volatile_cv", "diag_trigger", "kpi_shrinkage"]) delete defaults[k];
    await open(api({ ...SETTINGS, settings: { ...SETTINGS.settings, defaults: defaults as ShopSettingsPage["settings"]["defaults"] } }));
    expect(screen.queryByTestId("ops-diag")).toBeNull();
  });

  it("Nhật ký sentence and formats", () => {
    expect(fmtSetting("volatile_cv", 0.3)).toBe("CV > 30 %");
    expect(fmtSetting("diag_windows", [60, 14])).toBe("14 · 60 ngày");
    expect(describeSettingsAudit({ guard_band_mult: null }, { guard_band_mult: 2 })).toBe("Ngưỡng giữ ổn định: Mặc định → ×2 dao động");
  });
});
