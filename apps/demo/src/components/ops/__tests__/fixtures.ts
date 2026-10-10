import type { Overview, ShopSettingsPage, SimulationPage, StreamId, ViewSession } from "../../../lib/ops/types";

/** Ops fixtures shared by vitest and Playwright (numbers from the artboards). */

export const SHOP_ID = "11111111-2222-4333-8444-555555555555";
export const ME = { email: "thien.phung@app-juli.com", role: "admin" as const, role_label: "Admin" };

const row = (o: Partial<Overview["shops"][number]>): Overview["shops"][number] => ({
  shop_id: SHOP_ID,
  shop_name: "Mỹ phẩm Thảo Nhi",
  tiktok_shop_id: "VNSHOP1",
  owner_email: "thaonh…@…",
  owned_by_team: false,
  invite_pending: false,
  stage: "trial",
  stage_label: "Thử nghiệm",
  connection: "ok",
  active: true,
  last_poll_at: new Date().toISOString(),
  last_diagnosis_at: null,
  cards_open: 25,
  cards_approved_30d: 2,
  cards_rejected_30d: 6,
  approval_rate: 0.25,
  failed_runs_30d: 0,
  openai_cost_month_usd: 0.3,
  openai_cap_usd: null,
  openai_cap_reached: false,
  gmv_30d: 86_400_000,
  ...o,
});

export const OVERVIEW: Overview = {
  generated_at: "2026-10-10T08:00:00",
  totals: {
    accounts: 3,
    connected: 2,
    active: 1,
    disconnected: 1,
    cards_approved_30d: 23,
    approval_rate_30d: 0.72,
    openai_cost_month_usd: 8.5,
    openai_cap_alerts: 1,
  },
  shops: [
    row({}),
    row({
      shop_id: "22222222-2222-4333-8444-555555555555",
      shop_name: "Cửa hàng Mẫu Hoa Mai",
      owned_by_team: true,
      owner_email: "ops@app-juli.com",
      stage: "pilot",
      stage_label: "Pilot đặc biệt",
      failed_runs_30d: 2,
      openai_cost_month_usd: 5.2,
      openai_cap_usd: 5,
      openai_cap_reached: true,
      gmv_30d: 1_200_000_000,
    }),
    row({
      shop_id: "33333333-2222-4333-8444-555555555555",
      shop_name: "Đồ chơi Bé Na",
      connection: "none",
      stage: "self",
      stage_label: "Tự vận hành",
      approval_rate: null,
      gmv_30d: null,
    }),
  ],
};

export const SETTINGS: ShopSettingsPage = {
  shop: { shop_id: SHOP_ID, shop_name: "Mỹ phẩm Thảo Nhi", owner_email: "ops@app-juli.com", owned_by_team: true, staff_access_consent_at: null },
  settings: {
    shop_id: SHOP_ID,
    stage: "trial",
    stage_label: "Thử nghiệm",
    overrides: {
      card_daily_limit: null,
      card_weekly_limit: null,
      card_open_limit: null,
      enabled_streams: null,
      enabled_actions: null,
      content_cards_enabled: null,
      promotion_api_enabled: null,
      openai_model: null,
      openai_monthly_cap_usd: 5,
    },
    defaults: {
      card_daily_limit: 5,
      card_weekly_limit: 25,
      card_open_limit: 30,
      enabled_streams: ["product_card", "shop_tab", "seller_video", "seller_live"],
      enabled_actions: ["cover_image", "title", "description", "product_discount", "buy_more_save_more", "flash_sale", "shipping_discount", "video_script", "live_script"],
      content_cards_enabled: true,
      promotion_api_enabled: false,
      openai_model: "gpt-5.4-nano",
      openai_monthly_cap_usd: null,
    },
    updated_at: null,
    options: {
      stages: [
        { id: "trial", label: "Thử nghiệm" },
        { id: "self", label: "Tự vận hành" },
        { id: "pilot", label: "Pilot đặc biệt" },
      ],
      streams: [
        { id: "product_card", label: "Thẻ SP" },
        { id: "shop_tab", label: "Tab" },
        { id: "seller_video", label: "Video" },
        { id: "seller_live", label: "LIVE" },
      ],
      actions: ["cover_image", "title", "description", "product_discount", "buy_more_save_more", "flash_sale", "shipping_discount", "video_script", "live_script"],
      models: ["gpt-5.4-nano"],
    },
  },
  invites: [],
  audit: [
    {
      id: "a1",
      at: "2026-10-10T02:12:00",
      actor_email: "thien.phung@app-juli.com",
      shop_id: SHOP_ID,
      action: "settings_update",
      before: { openai_monthly_cap_usd: null },
      after: { openai_monthly_cap_usd: 5 },
    },
  ],
};

export const VIEW_SESSION: ViewSession = {
  shop: SETTINGS.shop,
  stage: "trial",
  read_only: true,
};

const band = (mean: number, pct: number, cv: number) => ({ p10: mean * (1 - pct / 100), p90: mean * (1 + pct / 100), mean, band_pct: pct, cv, days: 30 });

function stream(id: StreamId, name: string, v: [number, number, number, number], bands: [number, number, number, number], cv: number, locked: string[] = []) {
  const kpis = ["impressions", "ctr", "ctor", "aov"] as const;
  const labels = { impressions: "Hiển thị", ctr: "CTR", ctor: "CTOR", aov: "AOV" };
  return {
    stream: id,
    name,
    days_present: 30,
    gmv_per_day: v[0] * v[1] * v[2] * v[3],
    gmv_model_per_day: v[0] * v[1] * v[2] * v[3],
    impressions_cv: cv,
    stability: (cv < 0.15 ? "stable" : cv < 0.3 ? "medium" : "volatile") as "stable" | "medium" | "volatile",
    cells: kpis.map((k, i) => ({
      kpi: k,
      label: labels[k],
      value: v[i],
      trend_pct: [4.1, -1.2, -3.8, 0.3][i],
      band: band(v[i], bands[i], i === 0 ? cv : 0.05),
      locked: locked.includes(k),
      indirect: k === "impressions",
      actions: null as string | null,
    })),
  };
}

const card = stream("product_card", "Thẻ sản phẩm", [9913, 0.0444, 0.0514, 160_000], [12, 8, 14, 4], 0.12);
card.cells[1].actions = "ảnh bìa, tiêu đề";
card.cells[2].actions = "mô tả, giá, flash sale, voucher, phí ship";

export const SIMULATION: SimulationPage = {
  shop: SETTINGS.shop,
  stage: "pilot",
  window: 30,
  windows: [
    { days: 7, baseline_available: true, comparable: true, needs_days: 14, history_days: 60 },
    { days: 14, baseline_available: true, comparable: true, needs_days: 28, history_days: 60 },
    { days: 30, baseline_available: true, comparable: true, needs_days: 60, history_days: 60 },
    { days: 90, baseline_available: false, comparable: false, needs_days: 180, history_days: 60 },
  ],
  from: "2026-09-10",
  to: "2026-10-09",
  status: { days: 30, baseline_available: true, comparable: true, needs_days: 60, history_days: 60 },
  streams: [
    card,
    stream("shop_tab", "Tab cửa hàng", [2118, 0.0583, 0.0714, 167_000], [9, 7, 11, 5], 0.09),
    stream("seller_video", "Video", [5630, 0.0292, 0.0668, 173_000], [48, 22, 18, 6], 0.48, ["ctor", "aov"]),
    stream("seller_live", "LIVE", [1410, 0.0486, 0.071, 164_000], [35, 16, 20, 7], 0.35, ["aov"]),
  ],
  volatility: {
    product_card: {
      row_kind: "sản phẩm",
      rows: [
        { id: "p2", name: "KD-030 Kem dưỡng ceramide", impressions: band(1150, 40, 0.41), ctr: band(0.038, 10, 0.1), ctor: band(0.043, 15, 0.1), impressions_cv: 0.41, stability: "volatile" },
        { id: "p1", name: "SM-012 Son môi số 12", impressions: band(3850, 12, 0.11), ctr: band(0.032, 6, 0.05), ctor: band(0.054, 8, 0.05), impressions_cv: 0.11, stability: "stable" },
      ],
    },
  },
  lever_map: {},
  step_pct: 5,
  scenarios: [
    {
      id: "s1",
      name: "Mục tiêu Q4",
      deltas: { product_card: { ctor: 10 } },
      is_target: true,
      created_at: null,
      result: { streams: {} as never, total_base: 1, total_new: 1.062, delta_pct: 6.2, delta_per_day: 0, delta_per_month: 0 },
    },
  ],
};

export const SIMULATION_90: SimulationPage = {
  ...SIMULATION,
  window: 90,
  from: null,
  status: SIMULATION.windows[3],
  streams: [],
  volatility: {},
};
