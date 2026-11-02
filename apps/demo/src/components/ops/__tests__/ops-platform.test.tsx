import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ShopRules } from "../../../lib/quyet-dinh/types";
import { AUTH_SESSION_STORAGE_KEY } from "../../../lib/supabase-auth";
import { RulesEditor } from "../../quyet-dinh/rules-editor";
import { OpsCardGroups } from "../ops-card-groups";
import { OpsOverview } from "../ops-overview";
import { OpsShopSettings } from "../ops-shop-settings";
import { OpsViewAs } from "../ops-view-as";
import { ME, OVERVIEW, SETTINGS, SHOP_ID, VIEW_SESSION } from "./fixtures";

/** Migration 110: Ops shows each shop's platform; a Shopee shop's settings name Shopee and skip TikTok-only rows. */

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/ops",
  useSearchParams: () => new URLSearchParams(),
}));

beforeEach(() => {
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "t", tokenType: "bearer" }));
});

const SHOPEE_SETTINGS = { ...SETTINGS, shop: { ...SETTINGS.shop, platform: "shopee" } };

const unset = { value: null, set_by: null, set_by_user_id: null, set_at: null };
const RULES: ShopRules = {
  stability_band: {},
  product_cost: {},
  max_discount_pct: {},
  min_margin_pct: null,
  max_open_cards: { ...unset, value: 30 },
  auto_levers: { ...unset, value: ["title"] },
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
};

describe("platform label", () => {
  it("labels each overview row TikTok Shop or Shopee", async () => {
    const overview = {
      ...OVERVIEW,
      shops: [{ ...OVERVIEW.shops[0], platform: "tiktok" }, { ...OVERVIEW.shops[1], platform: "shopee" }, OVERVIEW.shops[2]],
    };
    render(<OpsOverview api={{ overview: async () => overview, disconnect: vi.fn() }} me={ME} />);
    await screen.findAllByTestId("ops-shop-row");
    expect(screen.getAllByTestId("ops-shop-platform").map((el) => el.textContent)).toEqual(["TikTok Shop", "Shopee", "TikTok Shop"]);
  });

  it("names the platform in the view-as header", async () => {
    const viewSession = vi.fn(async () => ({ ...VIEW_SESSION, shop: { ...VIEW_SESSION.shop, platform: "shopee" } }));
    const fetchStub = vi.fn(async () => new Response(JSON.stringify({ detail: "none" }), { status: 404 }));
    render(<OpsViewAs api={{ viewSession }} baseFetch={fetchStub as unknown as typeof fetch} me={ME} shopId={SHOP_ID} />);
    await waitFor(() => expect(screen.getByTestId("view-as-platform")).toHaveTextContent(/^Shopee · /));
    expect(screen.getByTestId("view-as-platform")).not.toHaveTextContent("TikTok");
  });

  it("keeps TikTok Shop in the view-as header of a TikTok shop", async () => {
    const viewSession = vi.fn(async () => VIEW_SESSION);
    const fetchStub = vi.fn(async () => new Response(JSON.stringify({ detail: "none" }), { status: 404 }));
    render(<OpsViewAs api={{ viewSession }} baseFetch={fetchStub as unknown as typeof fetch} me={ME} shopId={SHOP_ID} />);
    await waitFor(() => expect(screen.getByTestId("view-as-platform")).toHaveTextContent(/^TikTok Shop · /));
  });
});

describe("Cài đặt shop of a Shopee shop", () => {
  const api = (page: typeof SETTINGS) => ({
    settings: vi.fn(async () => page),
    putSettings: vi.fn(async () => ({ settings: page.settings })),
    resetSettings: vi.fn(async () => ({ settings: page.settings })),
    invite: vi.fn(async () => ({ data: {} as never, email_sent: true, accept_url: null })),
  });

  it("hides the TikTok promotions API and says Shopee", async () => {
    render(<OpsShopSettings api={api(SHOPEE_SETTINGS)} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByRole("heading", { name: "Mỹ phẩm Thảo Nhi · Cài đặt shop" })).toBeInTheDocument();
    expect(screen.getByTestId("ops-shop-platform")).toHaveTextContent("Shopee");
    expect(screen.getAllByTestId("ops-setting")).toHaveLength(6);
    expect(screen.queryByText("API khuyến mãi")).toBeNull();
  });

  it("a TikTok shop keeps the promotions API row", async () => {
    render(<OpsShopSettings api={api(SETTINGS)} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByRole("heading", { name: "Mỹ phẩm Thảo Nhi · Cài đặt shop" })).toBeInTheDocument();
    expect(screen.getByTestId("ops-shop-platform")).toHaveTextContent("TikTok Shop");
    expect(screen.getAllByTestId("ops-setting")).toHaveLength(7);
    expect(screen.getAllByText("API khuyến mãi").length).toBeGreaterThan(0);
  });
});

describe("Quy tắc of a Shopee shop", () => {
  it("names Shopee, drops the TikTok product / SKU wording and skips the GMV Max fields", () => {
    render(<RulesEditor fixedSetBy="team" onDelete={vi.fn()} onSave={vi.fn()} platform="shopee" rules={RULES} />);
    const group = screen.getByTestId("rules-off-api");
    expect(within(group).getByText("Thông tin Shopee không cung cấp")).toBeInTheDocument();
    expect(within(group).getByText(/^Shopee không cung cấp các thông tin này/)).toBeInTheDocument();
    expect(within(group).getByTestId("rule-program_fee_pct")).toHaveTextContent("Shopee chỉ báo phí này");
    expect(within(group).getByTestId("rule-joins_platform_campaigns")).toHaveTextContent("Shopee chưa cho Juli biết");
    expect(within(group).queryByTestId("rule-target_roas")).toBeNull();
    expect(within(group).queryByTestId("rule-gmv_max_daily_budget")).toBeNull();
    expect(within(group).getByTestId("rule-live_schedule")).toBeInTheDocument();
    expect(within(screen.getByTestId("rule-sku_cost")).getByLabelText("Mã SKU")).toBeInTheDocument();
    expect(within(screen.getByTestId("rule-product_cost")).getByLabelText("Mã sản phẩm")).toBeInTheDocument();
    expect(screen.getByTestId("rules-editor")).not.toHaveTextContent("TikTok");
    expect(screen.getByTestId("rules-editor")).not.toHaveTextContent("GMV Max");
  });

  it("a TikTok shop's rules read exactly as before", () => {
    render(<RulesEditor fixedSetBy="team" onDelete={vi.fn()} onSave={vi.fn()} platform="tiktok" rules={RULES} />);
    const group = screen.getByTestId("rules-off-api");
    expect(within(group).getByText("Thông tin TikTok không cung cấp")).toBeInTheDocument();
    expect(within(group).getByTestId("rule-gmv_max_daily_budget")).toHaveTextContent("Ngân sách GMV Max hằng ngày");
    expect(within(screen.getByTestId("rule-sku_cost")).getByLabelText("Mã SKU TikTok")).toBeInTheDocument();
    expect(within(screen.getByTestId("rule-product_cost")).getByLabelText("Mã sản phẩm TikTok")).toBeInTheDocument();
  });
});

describe("Nhóm thử nghiệm of a Shopee shop", () => {
  it("asks for product ids without naming TikTok", async () => {
    const load = vi.fn(async () => ({ enabled: true, groups: [] }) as never);
    render(<OpsCardGroups canEdit create={vi.fn()} load={load} platform="shopee" shopId={SHOP_ID} />);
    fireEvent.click(await screen.findByRole("button", { name: /Tạo nhóm/ }));
    const groups = screen.getByTestId("ops-groups");
    expect(within(groups).getByLabelText("Mã sản phẩm")).toBeInTheDocument();
    expect(groups).toHaveTextContent("Chủ shop tự tạo thay đổi trên Shopee");
    expect(groups).not.toHaveTextContent("TikTok");
  });
});
