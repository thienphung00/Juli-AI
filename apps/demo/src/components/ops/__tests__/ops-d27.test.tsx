import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CURRENT_SHOP_KEY } from "../../../lib/ops/current-shop";
import { fmtFreshness } from "../../../lib/ops/format";
import { AUTH_SESSION_STORAGE_KEY } from "../../../lib/supabase-auth";
import type { AuditEntry, SimulationPage } from "../../../lib/ops/types";
import { OpsOverview } from "../ops-overview";
import { OpsRules } from "../ops-rules";
import { OpsHeader } from "../ops-shell";
import { OpsShopSettings } from "../ops-shop-settings";
import { OpsSimulate } from "../ops-simulate";
import { OpsSimulateCurrent } from "../ops-simulate-current";
import { OpsAudit } from "../ops-staff-audit";
import { ME, OVERVIEW, SETTINGS, SHOP_ID, SIMULATION } from "./fixtures";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), usePathname: () => "/ops" }));

const VIEWER = { ...ME, role: "viewer" as const, role_label: "Xem" };
const NOW = new Date().toISOString();

beforeEach(() => {
  window.localStorage.clear();
});

function settingsApi() {
  return {
    settings: vi.fn(async () => SETTINGS),
    putSettings: vi.fn(async () => ({ settings: SETTINGS.settings })),
    resetSettings: vi.fn(async () => ({ settings: SETTINGS.settings })),
    invite: vi.fn(async () => ({ data: {} as never, email_sent: true, accept_url: null })),
  };
}

async function openSettings(a = settingsApi()) {
  render(<OpsShopSettings api={a} me={ME} shopId={SHOP_ID} />);
  await screen.findByRole("heading", { name: "Mỹ phẩm Thảo Nhi · Cài đặt shop" });
  return a;
}

/** Turn LIVE and Flash sale off and API khuyến mãi on (artboard OpsConfirm). */
function makeThreeChanges() {
  fireEvent.click(screen.getByRole("button", { name: "Sửa Luồng được đề xuất" }));
  fireEvent.click(screen.getByRole("button", { name: "LIVE", pressed: true }));
  fireEvent.click(screen.getByRole("button", { name: "Sửa Hành động bật" }));
  fireEvent.click(screen.getByRole("button", { name: "Flash sale", pressed: true }));
  fireEvent.click(screen.getByRole("button", { name: "Sửa API khuyến mãi" }));
  fireEvent.click(screen.getByRole("button", { name: "API khuyến mãi", pressed: false }));
}

describe("Cài đặt shop: every change is confirmed (D27.5, OpsConfirm.dc.html)", () => {
  it("a stage click opens before → after; Quay lại changes nothing", async () => {
    const a = await openSettings();
    fireEvent.click(screen.getByRole("radio", { name: /Tự vận hành/ }));
    const dialog = screen.getByRole("dialog", { name: "Đổi giai đoạn của Mỹ phẩm Thảo Nhi?" });
    expect(within(dialog).getByTestId("confirm-row")).toHaveTextContent("Giai đoạnThử nghiệm → Tự vận hành");
    expect(dialog).toHaveTextContent("Áp dụng ngay cho thẻ và lượt chạy mới. Nhật ký ghi 1 dòng.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Quay lại" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(a.putSettings).not.toHaveBeenCalled();
    expect(screen.getByRole("radio", { name: /Thử nghiệm/ })).toHaveAttribute("aria-checked", "true");
    // clicking the current stage asks nothing
    fireEvent.click(screen.getByRole("radio", { name: /Thử nghiệm/ }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("toggles are a draft: the bar counts and summarises; Bỏ thay đổi drops it", async () => {
    const a = await openSettings();
    expect(screen.queryByRole("region", { name: "Thay đổi chưa lưu" })).toBeNull();
    makeThreeChanges();
    const bar = screen.getByRole("region", { name: "Thay đổi chưa lưu" });
    expect(bar).toHaveTextContent("3 thay đổi chưa lưu");
    expect(within(bar).getByTestId("draft-summary")).toHaveTextContent("LIVE → Tắt · Flash sale → Tắt · API khuyến mãi: Tắt → Bật");
    expect(within(bar).getByRole("button", { name: "Lưu thay đổi (3)" })).toBeInTheDocument();
    // the row summary shows the draft value, nothing is sent yet
    expect(screen.getAllByTestId("ops-setting")[1]).toHaveTextContent("Thẻ SP · Tab · Video");
    expect(a.putSettings).not.toHaveBeenCalled();
    // switching one back takes it out of the draft
    fireEvent.click(screen.getByRole("button", { name: "LIVE", pressed: false }));
    expect(bar).toHaveTextContent("2 thay đổi chưa lưu");
    fireEvent.click(within(bar).getByRole("button", { name: "Bỏ thay đổi" }));
    expect(screen.queryByRole("region", { name: "Thay đổi chưa lưu" })).toBeNull();
    expect(screen.getByRole("button", { name: "Flash sale", pressed: true })).toBeInTheDocument();
    expect(a.putSettings).not.toHaveBeenCalled();
  });

  it("Lưu lists every change and sends ONE PUT with all changed keys", async () => {
    const a = await openSettings();
    makeThreeChanges();
    fireEvent.click(screen.getByRole("button", { name: "Sửa Model OpenAI" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Model OpenAI" }), { target: { value: "gpt-5.4-nano" } });
    fireEvent.click(screen.getByRole("button", { name: "Sửa Giới hạn chi phí OpenAI" }));
    fireEvent.change(screen.getByLabelText("Trần USD mỗi tháng"), { target: { value: "8" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu thay đổi (4)" }));
    const dialog = screen.getByRole("dialog", { name: "Lưu 4 thay đổi cho Mỹ phẩm Thảo Nhi?" });
    expect(screen.queryByRole("region", { name: "Thay đổi chưa lưu" })).toBeNull();
    const rows = within(dialog).getAllByTestId("confirm-row");
    expect(rows.map((r) => r.textContent)).toEqual([
      "LuồngLIVE → Tắt",
      "Hành độngFlash sale → Tắt",
      "API khuyến mãiTắt → Bật",
      "Trần chi phí OpenAI$5 / tháng → $8 / tháng",
    ]);
    expect(dialog).toHaveTextContent("Nhật ký ghi 1 dòng cho cả 4 thay đổi.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Xác nhận lưu" }));
    await waitFor(() => expect(a.putSettings).toHaveBeenCalledTimes(1));
    expect(a.putSettings).toHaveBeenCalledWith(SHOP_ID, {
      enabled_streams: ["product_card", "shop_tab", "seller_video"],
      enabled_actions: ["cover_image", "title", "description", "product_discount", "buy_more_save_more", "shipping_discount", "video_script", "live_script"],
      promotion_api_enabled: true,
      openai_monthly_cap_usd: 8,
    });
    expect(await screen.findByTestId("ops-toast")).toHaveTextContent("Đã lưu 4 thay đổi · ghi 1 dòng nhật ký");
    expect(screen.queryByRole("region", { name: "Thay đổi chưa lưu" })).toBeNull();
  });

  it("về mặc định on a row is a draft too (Ghi đè → Mặc định)", async () => {
    const a = await openSettings();
    fireEvent.click(screen.getByRole("button", { name: "về mặc định" }));
    expect(screen.getByRole("region", { name: "Thay đổi chưa lưu" })).toHaveTextContent("1 thay đổi chưa lưu");
    fireEvent.click(screen.getByRole("button", { name: "Lưu thay đổi (1)" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Xác nhận lưu" }));
    await waitFor(() => expect(a.putSettings).toHaveBeenCalledWith(SHOP_ID, { openai_monthly_cap_usd: null }));
  });
});

describe("Quy tắc edits are confirmed (D27.5)", () => {
  it("Quay lại sends nothing", async () => {
    window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "t", tokenType: "bearer" }));
    const unset = { value: null, set_by: null, set_by_user_id: null, set_at: null };
    const rules = {
      stability_band: {},
      product_cost: {},
      max_discount_pct: {},
      min_margin_pct: null,
      max_open_cards: { ...unset, value: 30 },
      auto_levers: { ...unset, value: ["title"] },
      protected_terms: { ...unset, value: [] },
      band_metrics: ["ctr"],
      listing_levers: ["title"],
      content_tone: { ...unset, value: "Vui vẻ", set_by: "seller" },
      banned_terms: { ...unset, value: [] },
    };
    const methods: string[] = [];
    const base = vi.fn(async (_url: string, init?: RequestInit) => {
      methods.push(init?.method ?? "GET");
      return new Response(JSON.stringify({ data: rules }), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    render(<OpsRules baseFetch={base as unknown as typeof fetch} canEdit shopId={SHOP_ID} shopName="Mỹ phẩm Thảo Nhi" />);
    const tone = await screen.findByTestId("rule-content_tone");
    fireEvent.change(within(tone).getByRole("textbox"), { target: { value: "Nghiêm túc" } });
    fireEvent.click(within(tone).getByRole("button", { name: "Lưu" }));
    const dialog = await screen.findByRole("dialog", { name: "Lưu quy tắc cho Mỹ phẩm Thảo Nhi?" });
    expect(within(dialog).getByTestId("confirm-row")).toHaveTextContent("Giọng vănVui vẻ → Nghiêm túc");
    fireEvent.click(within(dialog).getByRole("button", { name: "Quay lại" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(methods.filter((m) => m !== "GET")).toEqual([]);
  });
});

describe("Nhật ký (D27.4, D27.6, OpsLog.dc.html)", () => {
  const entry = (o: Partial<AuditEntry>): AuditEntry => ({
    id: "x",
    at: "2026-10-11T02:40:00",
    actor_email: "thien.phung@app-juli.com",
    shop_id: SHOP_ID,
    action: "settings_update",
    before: { stage: "trial" },
    after: { stage: "self" },
    ...o,
  });
  const ROWS: AuditEntry[] = [
    entry({ id: "1", kind: "config", merged_count: 4 }),
    entry({
      id: "2",
      kind: "config",
      merged_count: 1,
      before: { enabled_streams: null, promotion_api_enabled: false },
      after: { enabled_streams: ["product_card"], promotion_api_enabled: true },
    }),
    entry({ id: "3", kind: "view", action: "view_as_view", before: null, after: null, shop_id: "22222222-2222-4333-8444-555555555555" }),
    entry({ id: "4", kind: "system", actor_email: "system", action: "daily_precompute", shop_id: null, shop_name: null }),
  ];

  it("filters by kind (server and client), names the shop and shows the merged badge", async () => {
    const audit = vi.fn(async (_shop: string | null, kind?: string | null) => ({ data: kind ? ROWS.filter((r) => r.kind === kind) : ROWS }));
    render(<OpsAudit api={{ audit, overview: async () => OVERVIEW }} me={ME} />);
    expect(await screen.findAllByTestId("ops-audit-row")).toHaveLength(4);
    expect(audit).toHaveBeenLastCalledWith(null, null);
    for (const h of ["Lúc", "Ai", "Shop", "Thay đổi"]) expect(screen.getByText(h)).toBeInTheDocument();
    const [first, second, third, fourth] = screen.getAllByTestId("ops-audit-row");
    expect(first).toHaveTextContent("11/10 09:40");
    expect(first).toHaveTextContent("thien.phung");
    expect(await within(first).findByText("Mỹ phẩm Thảo Nhi")).toBeInTheDocument();
    expect(first).toHaveTextContent("Giai đoạn: Thử nghiệm → Tự vận hành");
    expect(within(first).getByTestId("audit-merged")).toHaveTextContent("gộp 4 lần đổi trong 10 phút");
    expect(within(second).queryByTestId("audit-merged")).toBeNull();
    expect(second).toHaveTextContent(/^.*Lưu \d thay đổi: .*bật API khuyến mãi/);
    expect(third).toHaveTextContent("Cửa hàng Mẫu Hoa Mai");
    expect(fourth).toHaveTextContent("hệ thống");
    expect(fourth).toHaveTextContent("Tất cả shop");
    expect(screen.getByText("Thời gian lưu")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Xem như shop" }));
    await waitFor(() => expect(audit).toHaveBeenLastCalledWith(null, "view"));
    await waitFor(() => expect(screen.getAllByTestId("ops-audit-row")).toHaveLength(1));
    expect(screen.getByRole("button", { name: "Xem như shop" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Hệ thống" }));
    // "Hệ thống" also holds data_refresh (the backend's `view` kind): both kinds are asked for.
    await waitFor(() => expect(audit).toHaveBeenCalledWith(null, "system"));
    await waitFor(() => expect(audit).toHaveBeenLastCalledWith(null, "view"));
    await waitFor(() => expect(screen.getAllByTestId("ops-audit-row")).toHaveLength(1));
    expect(screen.getByTestId("ops-audit-row")).toHaveAttribute("data-kind", "system");
    fireEvent.click(screen.getByRole("button", { name: "Cấu hình" }));
    await waitFor(() => expect(screen.getAllByTestId("ops-audit-row")).toHaveLength(2));
  });

  it("an older backend (no kind) is still filtered by the action", async () => {
    const old = ROWS.map((r) => ({ ...r, kind: undefined, merged_count: undefined }));
    render(<OpsAudit api={{ audit: async () => ({ data: old }) }} me={ME} />);
    await screen.findAllByTestId("ops-audit-row");
    fireEvent.click(screen.getByRole("button", { name: "Xem như shop" }));
    await waitFor(() => expect(screen.getAllByTestId("ops-audit-row")).toHaveLength(1));
    expect(screen.queryByTestId("audit-merged")).toBeNull();
  });
});

describe("Mô phỏng in one place (D27.8)", () => {
  const sim = (): SimulationPage => ({ ...SIMULATION, generated_at: NOW, data_through: "2026-10-10" });

  it("the shop nav has no Mô phỏng; the main nav's goes to /ops/mo-phong", () => {
    const { unmount } = render(<OpsHeader active="settings" me={ME} shopId={SHOP_ID} />);
    expect(screen.queryByRole("link", { name: "Mô phỏng" })).toBeNull();
    unmount();
    render(<OpsHeader active="overview" me={ME} />);
    expect(screen.getByRole("link", { name: "Mô phỏng" })).toHaveAttribute("href", "/ops/mo-phong");
  });

  it("Tổng quan: no per-row Mô phỏng; search by name; choosing a shop is remembered", async () => {
    render(<OpsOverview api={{ overview: async () => OVERVIEW, disconnect: vi.fn() }} me={ME} />);
    const rows = await screen.findAllByTestId("ops-shop-row");
    for (const row of rows) expect(within(row).queryByRole("link", { name: "Mô phỏng" })).toBeNull();
    fireEvent.change(screen.getByPlaceholderText("Tên shop, mã shop"), { target: { value: "hoa mai" } });
    expect(screen.getAllByTestId("ops-shop-row")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Cửa hàng Mẫu Hoa Mai" }));
    expect(JSON.parse(window.localStorage.getItem(CURRENT_SHOP_KEY) ?? "{}")).toEqual({
      id: "22222222-2222-4333-8444-555555555555",
      name: "Cửa hàng Mẫu Hoa Mai",
    });
    expect(screen.getByRole("button", { name: "Cửa hàng Mẫu Hoa Mai" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("ops-shop-row")).toHaveTextContent("đang chọn");
    // opening Cài đặt also chooses the shop
    fireEvent.change(screen.getByPlaceholderText("Tên shop, mã shop"), { target: { value: "" } });
    fireEvent.click(within(screen.getAllByTestId("ops-shop-row")[0]).getByRole("link", { name: "Cài đặt" }));
    expect(JSON.parse(window.localStorage.getItem(CURRENT_SHOP_KEY) ?? "{}").id).toBe(SHOP_ID);
  });

  it("Tổng quan marks the remembered shop on load and survives broken storage", async () => {
    window.localStorage.setItem(CURRENT_SHOP_KEY, JSON.stringify({ id: SHOP_ID, name: "Mỹ phẩm Thảo Nhi" }));
    const { unmount } = render(<OpsOverview api={{ overview: async () => OVERVIEW, disconnect: vi.fn() }} me={ME} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Mỹ phẩm Thảo Nhi" })).toHaveAttribute("aria-pressed", "true"));
    unmount();
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    render(<OpsOverview api={{ overview: async () => OVERVIEW, disconnect: vi.fn() }} me={ME} />);
    fireEvent.click(await screen.findByRole("button", { name: "Mỹ phẩm Thảo Nhi" }));
    expect(screen.getByRole("button", { name: "Mỹ phẩm Thảo Nhi" })).toHaveAttribute("aria-pressed", "true");
    spy.mockRestore();
    set.mockRestore();
  });

  it("/ops/mo-phong without a remembered shop points to Tổng quan", () => {
    render(<OpsSimulateCurrent me={ME} />);
    expect(screen.getByText("Mô phỏng", { selector: "[aria-current='page']" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Chọn một shop ở Tổng quan ›" })).toHaveAttribute("href", "/ops");
    expect(screen.queryByTestId("simulate-shop-link")).toBeNull();
  });

  it("/ops/mo-phong opens the remembered shop's simulation in place", async () => {
    window.localStorage.setItem(CURRENT_SHOP_KEY, JSON.stringify({ id: SHOP_ID, name: "Mỹ phẩm Thảo Nhi" }));
    const simulation = vi.fn(async () => sim());
    render(<OpsSimulateCurrent api={{ simulation, createScenario: vi.fn(), setTarget: vi.fn() }} me={ME} />);
    expect(await screen.findByRole("heading", { name: "Mô phỏng · Mỹ phẩm Thảo Nhi" })).toBeInTheDocument();
    expect(simulation).toHaveBeenCalledWith(SHOP_ID, 30);
    expect(screen.getByRole("link", { name: "Đổi shop ở Tổng quan ›" })).toHaveAttribute("href", "/ops");
    expect(screen.getByText("Mô phỏng", { selector: "[aria-current='page']" })).toBeInTheDocument();
    // D28: Tổng quan · Mô phỏng · Chi phí · Thời hạn · Nhân viên · Nhật ký.
    expect(screen.getByRole("navigation", { name: "Ops" })).toHaveTextContent("Tổng quanMô phỏngChi phíThời hạnNhân viênNhật ký");
  });
});

describe("freshness line + Làm mới (D27.1)", () => {
  it("formats data-through and update time; nothing without generated_at", () => {
    const now = new Date("2026-10-11T05:00:00Z");
    expect(fmtFreshness({ generated_at: "2026-10-11T00:12:00Z", data_through: "2026-10-10" }, now)).toBe(
      "Số liệu đến hết 10/10 · cập nhật lúc 07:12 hôm nay",
    );
    expect(fmtFreshness({ generated_at: "2026-10-09T00:12:00", data_through: "2026-10-08" }, now)).toBe(
      "Số liệu đến hết 08/10 · cập nhật lúc 07:12 09/10",
    );
    expect(fmtFreshness({ data_through: "2026-10-10" }, now)).toBeNull();
    expect(fmtFreshness(null, now)).toBeNull();
  });

  it("Tổng quan: Làm mới calls the refresh endpoint and shows Đang tính lại…", async () => {
    let finish: (v: typeof OVERVIEW) => void = () => undefined;
    const refreshOverview = vi.fn(() => new Promise<typeof OVERVIEW>((r) => (finish = r)));
    render(
      <OpsOverview api={{ overview: async () => ({ ...OVERVIEW, generated_at: NOW, data_through: "2026-10-10" }), disconnect: vi.fn(), refreshOverview }} me={ME} />,
    );
    const line = await screen.findByTestId("ops-freshness");
    expect(line).toHaveTextContent(/Số liệu đến hết 10\/10 · cập nhật lúc \d\d:\d\d hôm nay/);
    fireEvent.click(within(line).getByRole("button", { name: "Làm mới" }));
    expect(refreshOverview).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("ops-freshness")).toHaveTextContent("Đang tính lại…");
    expect(within(screen.getByTestId("ops-freshness")).queryByRole("button")).toBeNull();
    finish({ ...OVERVIEW, generated_at: NOW, data_through: "2026-10-11" });
    await waitFor(() => expect(screen.getByTestId("ops-freshness")).toHaveTextContent("Số liệu đến hết 11/10"));
  });

  it("Tổng quan: no line on an older backend; Xem cannot refresh", async () => {
    const old = { ...OVERVIEW, generated_at: undefined };
    const { unmount } = render(<OpsOverview api={{ overview: async () => old, disconnect: vi.fn(), refreshOverview: vi.fn() }} me={ME} />);
    await screen.findAllByTestId("ops-shop-row");
    expect(screen.queryByTestId("ops-freshness")).toBeNull();
    unmount();
    render(<OpsOverview api={{ overview: async () => ({ ...OVERVIEW, generated_at: NOW }), disconnect: vi.fn(), refreshOverview: vi.fn() }} me={VIEWER} />);
    const line = await screen.findByTestId("ops-freshness");
    expect(within(line).queryByRole("button", { name: "Làm mới" })).toBeNull();
  });

  it("Mô phỏng: Làm mới refreshes this shop at the current window; Xem cannot", async () => {
    const refreshSimulation = vi.fn(async () => ({ ...SIMULATION, generated_at: NOW, data_through: "2026-10-11" }));
    const api = { simulation: async () => ({ ...SIMULATION, generated_at: NOW, data_through: "2026-10-10" }), createScenario: vi.fn(), setTarget: vi.fn(), refreshSimulation };
    const { unmount } = render(<OpsSimulate api={api} me={ME} shopId={SHOP_ID} />);
    const line = await screen.findByTestId("ops-freshness");
    expect(line).toHaveTextContent("Số liệu đến hết 10/10");
    fireEvent.click(within(line).getByRole("button", { name: "Làm mới" }));
    await waitFor(() => expect(refreshSimulation).toHaveBeenCalledWith(SHOP_ID, 30));
    await waitFor(() => expect(screen.getByTestId("ops-freshness")).toHaveTextContent("Số liệu đến hết 11/10"));
    unmount();
    render(<OpsSimulate api={api} me={VIEWER} shopId={SHOP_ID} />);
    expect(within(await screen.findByTestId("ops-freshness")).queryByRole("button", { name: "Làm mới" })).toBeNull();
  });
});
