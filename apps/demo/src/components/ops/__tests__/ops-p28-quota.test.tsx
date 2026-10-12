import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fmtSetting } from "../../../lib/ops/setting-changes";
import type { ShopSettingsPage } from "../../../lib/ops/types";
import { OpsShopSettings } from "../ops-shop-settings";
import { ME, SETTINGS, SHOP_ID } from "./fixtures";

/** P28 (D33): "Nhiều thẻ mỗi ô" — the per-shop quota mode toggle and the open cards per cell. */

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), usePathname: () => "/ops" }));

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    // Some Node versions expose no usable localStorage in jsdom; nothing to clear then.
  }
});

function page(mode: boolean | null, cells?: Record<string, number>): ShopSettingsPage {
  return {
    ...SETTINGS,
    settings: {
      ...SETTINGS.settings,
      overrides: { ...SETTINGS.settings.overrides, card_quota_mode: mode, card_quota_per_cell: null, card_quota_max_open: null },
      defaults: { ...SETTINGS.settings.defaults, card_quota_mode: false, card_quota_per_cell: 5, card_quota_max_open: 40 },
    },
    ...(cells ? { card_cells: cells } : {}),
  };
}

function api(p: ShopSettingsPage) {
  return {
    settings: vi.fn(async () => p),
    putSettings: vi.fn(async () => ({ settings: p.settings })),
    resetSettings: vi.fn(async () => ({ settings: p.settings })),
    invite: vi.fn(async () => ({ data: {} as never, email_sent: true, accept_url: null })),
  };
}

async function open(p: ShopSettingsPage) {
  const a = api(p);
  render(<OpsShopSettings api={a} me={ME} shopId={SHOP_ID} />);
  await screen.findByRole("heading", { name: "Mỹ phẩm Thảo Nhi · Cài đặt shop" });
  return a;
}

describe("Nhiều thẻ mỗi ô (D33)", () => {
  it("is hidden when the backend sends no quota keys", async () => {
    await open(SETTINGS);
    expect(screen.queryByTestId("ops-quota")).toBeNull();
  });

  it("shows the mode off by default and turns it on through the draft + confirm", async () => {
    const a = await open(page(null));
    const section = screen.getByTestId("ops-quota");
    const rows = within(section).getAllByTestId("ops-setting");
    expect(rows.map((r) => within(r).getByRole("button", { name: /^Sửa / }).textContent)).toEqual(["Tắt", "5 thẻ/ô", "40 thẻ mở"]);
    expect(within(section).queryByTestId("ops-quota-cells")).toBeNull();
    fireEvent.click(within(section).getByRole("button", { name: "Sửa Nhiều thẻ mỗi ô" }));
    fireEvent.click(within(section).getByRole("button", { name: "Nhiều thẻ mỗi ô" }));
    const bar = screen.getByRole("region", { name: "Thay đổi chưa lưu" });
    fireEvent.click(within(bar).getByRole("button", { name: "Lưu thay đổi (1)" }));
    const dialog = screen.getByRole("dialog", { name: "Lưu 1 thay đổi cho Mỹ phẩm Thảo Nhi?" });
    expect(within(dialog).getAllByTestId("confirm-row").map((r) => r.textContent)).toEqual(["Nhiều thẻ mỗi ôTắt → Bật"]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Xác nhận lưu" }));
    await waitFor(() => expect(a.putSettings).toHaveBeenCalledWith(SHOP_ID, { card_quota_mode: true }));
  });

  it("lists the open cards per cell while the mode is on", async () => {
    await open(page(true, { "ctr@product_card": 5, "ctor@total": 2, content_video: 1 }));
    const cells = screen.getByTestId("ops-quota-cells");
    expect(cells).toHaveTextContent("CTR · Thẻ sản phẩm: 5/5");
    expect(cells).toHaveTextContent("CTOR · tất cả kênh: 2/5");
    expect(cells).toHaveTextContent("Video (nội dung): 1/5");
  });

  it("formats the quota values", () => {
    expect(fmtSetting("card_quota_per_cell", 7)).toBe("7 thẻ/ô");
    expect(fmtSetting("card_quota_max_open", 40)).toBe("40 thẻ mở");
    expect(fmtSetting("card_quota_mode", true)).toBe("Bật");
  });
});
