import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fmtSetting } from "../../../lib/ops/setting-changes";
import type { CardGroupsPage, ShopSettingsPage } from "../../../lib/ops/types";
import { comparisonText } from "../ops-card-groups";
import { OpsShopSettings } from "../ops-shop-settings";
import { ME, SETTINGS, SHOP_ID } from "./fixtures";

/** P30 (D34 / D39.3): "Nhóm thử nghiệm (đối chứng chậm)" — the toggle and the group view. */

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), usePathname: () => "/ops" }));

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    // Some Node versions expose no usable localStorage in jsdom.
  }
});

const PAGE: ShopSettingsPage = {
  ...SETTINGS,
  settings: {
    ...SETTINGS.settings,
    overrides: { ...SETTINGS.settings.overrides, card_quota_mode: true, card_quota_per_cell: null, card_quota_max_open: null, card_groups: null },
    defaults: { ...SETTINGS.settings.defaults, card_quota_mode: false, card_quota_per_cell: 5, card_quota_max_open: 40, card_groups: null },
  },
};

const GROUPS: CardGroupsPage = {
  enabled: true,
  groups: [
    {
      id: "g1",
      key: "ctr|cover_image|product_card",
      label: "CTR · Ảnh bìa · Thẻ sản phẩm",
      metric: "ctr",
      lever: "cover_image",
      channel: "product_card",
      launched_on: "2026-10-13",
      release_on: "2026-10-27",
      seed: 4242,
      status: "measured",
      treated: 2,
      control: 1,
      members: [
        { product_id: "p1", product_title: "Son 01", arm: "control", card_id: "c1", card_status: "active", surfaced_at: null, approved: false, released_at: "2026-10-27T02:00:00" },
        { product_id: "p2", product_title: "Son 02", arm: "treated", card_id: "c2", card_status: "approved", surfaced_at: "2026-10-13T02:00:00", approved: true, released_at: null },
        { product_id: "p3", product_title: "Son 03", arm: "treated", card_id: "c3", card_status: "expired", surfaced_at: "2026-10-13T02:00:00", approved: false, released_at: null },
      ],
      verdict: {
        as_of: "2026-10-26",
        window_days: 14,
        primary: { n_treated: 5, n_control: 3, label: "Sơ bộ", median_treated: 9, median_control: 2, difference: 7, interval: [2.1, 11.8], strength: "clear", strength_label: "Thay đổi rõ" },
        approved_only: { n_treated: 1, n_control: 3, label: "Chưa đủ cơ sở", median_treated: null, median_control: null, difference: null, interval: null, strength: null, strength_label: null },
        products: [
          { product_id: "p1", arm: "control", approved: false, before: 0.04, after: 0.041, change_pct: 2.5 },
          { product_id: "p2", arm: "treated", approved: true, before: 0.04, after: 0.044, change_pct: 10 },
        ],
      },
      seller_sentence: "Nhóm 3 sản phẩm đổi ảnh bìa: lượt nhấp tăng khoảng 7 % so với các sản phẩm chưa đổi (sơ bộ)",
    },
  ],
};

function api(groups: CardGroupsPage | null = GROUPS) {
  return {
    settings: vi.fn(async () => PAGE),
    putSettings: vi.fn(async () => ({ settings: PAGE.settings })),
    resetSettings: vi.fn(async () => ({ settings: PAGE.settings })),
    invite: vi.fn(async () => ({ data: {} as never, email_sent: true, accept_url: null })),
    ...(groups ? { groups: vi.fn(async () => groups) } : {}),
  };
}

async function open(a = api()) {
  render(<OpsShopSettings api={a} me={ME} shopId={SHOP_ID} />);
  await screen.findByRole("heading", { name: "Mỹ phẩm Thảo Nhi · Cài đặt shop" });
  return a;
}

describe("Nhóm thử nghiệm (D34)", () => {
  it("the toggle follows Nhiều thẻ mỗi ô until set, and is drafted like the other keys", async () => {
    const a = await open();
    const section = screen.getByTestId("ops-quota");
    const button = within(section).getByRole("button", { name: "Sửa Nhóm thử nghiệm (đối chứng chậm)" });
    expect(button).toHaveTextContent("Theo Nhiều thẻ mỗi ô (Bật)");
    fireEvent.click(button);
    fireEvent.click(within(section).getByRole("button", { name: "Nhóm thử nghiệm" }));
    const bar = screen.getByRole("region", { name: "Thay đổi chưa lưu" });
    fireEvent.click(within(bar).getByRole("button", { name: "Lưu thay đổi (1)" }));
    const dialog = screen.getByRole("dialog", { name: "Lưu 1 thay đổi cho Mỹ phẩm Thảo Nhi?" });
    expect(within(dialog).getAllByTestId("confirm-row").map((r) => r.textContent)).toEqual(["Nhóm thử nghiệm (đối chứng chậm)Theo Nhiều thẻ mỗi ô → Tắt"]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Xác nhận lưu" }));
    await waitFor(() => expect(a.putSettings).toHaveBeenCalledWith(SHOP_ID, { card_groups: false }));
  });

  it("lists groups with arms, launch, release, verdict and interval; members on click", async () => {
    const a = await open();
    const view = await screen.findByTestId("ops-groups");
    expect(a.groups).toHaveBeenCalledWith(SHOP_ID);
    const [group] = within(view).getAllByTestId("ops-group");
    expect(group).toHaveTextContent("CTR · Ảnh bìa · Thẻ sản phẩm");
    expect(group).toHaveTextContent("Đã đo · bắt đầu 13/10/2026 · trả thẻ đối chứng 27/10/2026");
    expect(group).toHaveTextContent("2 áp dụng · 1 đối chứng");
    expect(group).toHaveTextContent("+7,0 điểm % (khoảng +2,1 → +11,8) · Thay đổi rõ · Sơ bộ · 5 áp dụng · 3 đối chứng");
    expect(group).toHaveTextContent("Chỉ thẻ đã duyệt: Chưa đủ cơ sở (1 áp dụng · 3 đối chứng)");
    expect(group).toHaveTextContent("Seed 4242");
    fireEvent.click(within(group).getByRole("button", { name: /CTR · Ảnh bìa/ }));
    const rows = within(group).getAllByRole("row");
    expect(rows.map((r) => r.textContent)).toEqual([
      "Sản phẩmNhómThẻThay đổi",
      "Son 01Đối chứngđã trả thẻ+2,5 %",
      "Son 02Áp dụngđã hiện · đã duyệt+10,0 %",
      "Son 03Áp dụngđã hiện—",
    ]);
  });

  it("no groups API (older client) shows no section; an empty shop says so", async () => {
    await open(api(null));
    expect(screen.queryByTestId("ops-groups")).toBeNull();
  });

  it("formats", async () => {
    expect(fmtSetting("card_groups", null)).toBe("Theo Nhiều thẻ mỗi ô");
    expect(fmtSetting("card_groups", true)).toBe("Bật");
    expect(comparisonText(null)).toBe("—");
  });
});
