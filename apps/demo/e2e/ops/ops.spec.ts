import { expect, test, type Page } from "@playwright/test";

import { COSTS, MB_SHOP_ID, MB_TERMS, ME, OVERVIEW, SETTINGS, SHOP_ID, SIMULATION, TERMS, VIEW_SESSION } from "../../src/components/ops/__tests__/fixtures";

/**
 * P16 Juli Ops pages (artboards docs/product/design/ops). Local host serves the
 * ops routes (middleware); the API is stubbed; no seller `/v1/demo` request is
 * ever made, and "Xem như shop" never sends a write.
 */

const unset = { value: null, set_by: null, set_by_user_id: null, set_at: null };
const RULES = {
  stability_band: {},
  product_cost: {},
  max_discount_pct: {},
  min_margin_pct: null,
  max_open_cards: { ...unset, value: 30 },
  auto_levers: { ...unset, value: ["title"] },
  protected_terms: { ...unset, value: [] },
  band_metrics: ["ctr"],
  listing_levers: ["title", "description", "attributes", "image"],
};

const AUDIT = [
  {
    id: "1",
    at: "2026-10-11T02:40:00",
    actor_email: "thien.phung@app-juli.com",
    shop_id: SHOP_ID,
    shop_name: "Mỹ phẩm Thảo Nhi",
    action: "settings_update",
    before: { stage: "trial" },
    after: { stage: "self" },
    kind: "config",
    merged_count: 4,
  },
  {
    id: "2",
    at: "2026-10-11T01:55:00",
    actor_email: "thien.phung@app-juli.com",
    shop_id: SHOP_ID,
    shop_name: "Mỹ phẩm Thảo Nhi",
    action: "view_as_view",
    before: null,
    after: null,
    kind: "view",
    merged_count: 1,
  },
];

async function stub(page: Page) {
  const writes: string[] = [];
  const seller: string[] = [];
  const puts: unknown[] = [];
  const posts: string[] = [];
  await page.addInitScript(() => {
    window.localStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
  });
  await page.route("**/v1/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path.startsWith("/v1/demo")) seller.push(path);
    if (req.method() !== "GET" && path.includes("/view/")) writes.push(path);
    if (req.method() === "POST" && !path.includes("/view/")) posts.push(path);
    const fresh = { generated_at: new Date().toISOString(), data_through: "2026-10-10" };
    if (path === "/v1/ops/me") return json(ME);
    if (path === "/v1/ops/overview" || path === "/v1/ops/overview/refresh") return json({ ...OVERVIEW, ...fresh });
    if (path === "/v1/ops/audit") {
      const kind = url.searchParams.get("kind");
      return json({ data: kind ? AUDIT.filter((r) => r.kind === kind) : AUDIT });
    }
    if (path === `/v1/ops/shops/${SHOP_ID}/settings`) {
      if (req.method() === "PUT") puts.push(req.postDataJSON());
      return json(req.method() === "PUT" ? { settings: SETTINGS.settings } : SETTINGS);
    }
    if (path === `/v1/ops/shops/${SHOP_ID}/view-session`) return json(VIEW_SESSION);
    if (path === `/v1/ops/shops/${SHOP_ID}/view/decisions`) return json({ data: [] });
    if (path === `/v1/ops/shops/${SHOP_ID}/view/runs`) return json({ data: [] });
    if (path === `/v1/ops/shops/${SHOP_ID}/simulation` || path === `/v1/ops/shops/${SHOP_ID}/simulation/refresh`) return json({ ...SIMULATION, ...fresh });
    if (path === `/v1/ops/shops/${SHOP_ID}/rules`) return json({ data: RULES });
    // D28.3 tab Chi phí + the banner on every page; D28.4 tab Thời hạn.
    if (path === "/v1/ops/costs/system") return json({ system: COSTS.system });
    if (path === "/v1/ops/costs") return json(COSTS);
    if (path === "/v1/ops/costs/system-cap" && req.method() === "PUT") {
      puts.push(req.postDataJSON());
      return json({ system: { ...COSTS.system, cap_usd: 80, cap_is_default: false, pct: 0.5125, level: null } });
    }
    if (path.endsWith("/openai-cap") && req.method() === "PUT") {
      puts.push(req.postDataJSON());
      return json({ shop_id: SHOP_ID, cap_usd: 20, is_custom: true });
    }
    if (path === "/v1/ops/terms") return json(TERMS);
    if (path === `/v1/ops/shops/${MB_SHOP_ID}/terms`) {
      if (req.method() === "POST") puts.push(req.postDataJSON());
      return json(MB_TERMS);
    }
    if (/^\/v1\/ops\/shops\/[^/]+\/terms$/.test(path)) return json({ ...MB_TERMS, periods: [] });
    if (path === `/v1/ops/shops/${SHOP_ID}/view/term`) return json({ data: { state: "grace", expires_on: "2026-10-09", days_left: -3, grace_days_left: 4 } });
    return json({ detail: "not stubbed" }, 404);
  });
  return { writes, seller, puts, posts };
}

test("Tổng quan lists shops with totals and the Admin-only Huỷ kết nối", async ({ page }) => {
  const { seller } = await stub(page);
  await page.goto("/ops");
  await expect(page.getByRole("heading", { name: "Gian hàng đã kết nối" })).toBeVisible();
  await expect(page.getByTestId("ops-shop-row")).toHaveCount(3);
  await expect(page.getByTestId("cap-badge")).toContainText("Chạm giới hạn");
  await expect(page.getByTestId("ops-freshness")).toContainText("Số liệu đến hết 10/10 · cập nhật lúc");
  await expect(page.getByRole("link", { name: "Mô phỏng" })).toHaveCount(1);
  await page.getByRole("button", { name: "Huỷ kết nối" }).first().click();
  await expect(page.getByRole("dialog")).toContainText("Seller nhận email báo đã huỷ kết nối.");
  await page.getByRole("button", { name: "Quay lại" }).click();
  await page.getByRole("button", { name: "Pilot đặc biệt" }).click();
  await expect(page.getByTestId("ops-shop-row")).toHaveCount(1);
  expect(seller).toEqual([]);
});

test("Cài đặt shop shows stage, overrides, invite and the audit log", async ({ page }) => {
  await stub(page);
  await page.goto(`/ops/shops/${SHOP_ID}`);
  await expect(page.getByRole("heading", { name: "Mỹ phẩm Thảo Nhi · Cài đặt shop" })).toBeVisible();
  await expect(page.getByTestId("ops-setting")).toHaveCount(7);
  await expect(page.getByText("Ghi đè")).toBeVisible();
  await expect(page.getByRole("button", { name: "Mời seller" })).toBeVisible();
  await expect(page.getByTestId("ops-audit-row")).toHaveCount(1);
  await expect(page.getByTestId("ops-rules").getByTestId("rules-editor")).toBeVisible();
  await expect(page.getByTestId("rule-content_tone")).toBeVisible();
});

test("Cài đặt shop: stage confirm, then a draft saved in one PUT (D27.5)", async ({ page }) => {
  const { puts } = await stub(page);
  await page.goto(`/ops/shops/${SHOP_ID}`);
  await page.getByRole("radio", { name: /Tự vận hành/ }).click();
  const stage = page.getByRole("dialog", { name: "Đổi giai đoạn của Mỹ phẩm Thảo Nhi?" });
  await expect(stage).toContainText("Thử nghiệm → Tự vận hành");
  await stage.getByRole("button", { name: "Quay lại" }).click();
  await expect(stage).toHaveCount(0);
  expect(puts).toEqual([]);

  await page.getByRole("button", { name: "Sửa Luồng được đề xuất" }).click();
  await page.getByRole("button", { name: "LIVE", exact: true }).click();
  await page.getByRole("button", { name: "Sửa API khuyến mãi" }).click();
  await page.getByRole("button", { name: "API khuyến mãi", exact: true }).click();
  const bar = page.getByRole("region", { name: "Thay đổi chưa lưu" });
  await expect(bar).toContainText("2 thay đổi chưa lưu");
  await expect(bar).toContainText("LIVE → Tắt · API khuyến mãi: Tắt → Bật");
  await bar.getByRole("button", { name: "Lưu thay đổi (2)" }).click();
  const save = page.getByRole("dialog", { name: "Lưu 2 thay đổi cho Mỹ phẩm Thảo Nhi?" });
  await expect(save.getByTestId("confirm-row")).toHaveCount(2);
  await save.getByRole("button", { name: "Xác nhận lưu" }).click();
  await expect(page.getByTestId("ops-toast")).toContainText("Đã lưu 2 thay đổi · ghi 1 dòng nhật ký");
  expect(puts).toEqual([{ changes: { enabled_streams: ["product_card", "shop_tab", "seller_video"], promotion_api_enabled: true } }]);
});

test("Cài đặt shop: Chẩn đoán & KPI tunables go through the draft bar and one PUT (D29.11)", async ({ page }) => {
  const { puts } = await stub(page);
  await page.goto(`/ops/shops/${SHOP_ID}`);
  const diag = page.getByTestId("ops-diag");
  await diag.getByRole("button", { name: /Chẩn đoán & KPI/ }).click();
  await expect(diag.getByTestId("ops-setting")).toHaveCount(6);
  await expect(diag.getByTestId("ops-setting").first()).toContainText("14 · 30 · 60 ngày");
  await page.getByRole("button", { name: "Sửa Ngưỡng lưu lượng ổn định" }).click();
  await page.getByRole("spinbutton", { name: "Ngưỡng lưu lượng ổn định" }).fill("25");
  const bar = page.getByRole("region", { name: "Thay đổi chưa lưu" });
  await expect(bar).toContainText("1 thay đổi chưa lưu");
  await bar.getByRole("button", { name: "Lưu thay đổi (1)" }).click();
  const save = page.getByRole("dialog", { name: "Lưu 1 thay đổi cho Mỹ phẩm Thảo Nhi?" });
  await expect(save.getByTestId("confirm-row")).toContainText("CV > 30 % → CV > 25 %");
  await save.getByRole("button", { name: "Xác nhận lưu" }).click();
  await expect(page.getByTestId("ops-toast")).toContainText("Đã lưu 1 thay đổi · ghi 1 dòng nhật ký");
  expect(puts).toEqual([{ changes: { volatile_cv: 0.25 } }]);
});

test("Nhật ký filters by kind and shows merged rows (D27.4, D27.6)", async ({ page }) => {
  await stub(page);
  await page.goto("/ops/nhat-ky");
  await expect(page.getByTestId("ops-audit-row")).toHaveCount(2);
  await expect(page.getByTestId("audit-merged")).toContainText("gộp 4 lần đổi trong 10 phút");
  await page.getByRole("button", { name: "Xem như shop" }).click();
  await expect(page.getByTestId("ops-audit-row")).toHaveCount(1);
  await expect(page.getByText("Thời gian lưu")).toBeVisible();
});

test("Mô phỏng opens the shop chosen in Tổng quan (D27.8)", async ({ page }) => {
  const { posts } = await stub(page);
  await page.goto("/ops/mo-phong");
  await expect(page.getByRole("link", { name: "Chọn một shop ở Tổng quan ›" })).toBeVisible();
  await page.getByRole("link", { name: "Chọn một shop ở Tổng quan ›" }).click();
  await page.getByPlaceholder("Tên shop, mã shop").fill("thảo nhi");
  await expect(page.getByTestId("ops-shop-row")).toHaveCount(1);
  await page.getByRole("button", { name: "Mỹ phẩm Thảo Nhi" }).click();
  await page.getByRole("navigation", { name: "Ops" }).getByRole("link", { name: "Mô phỏng" }).click();
  await expect(page).toHaveURL(/\/ops\/mo-phong$/);
  await expect(page.getByRole("heading", { name: "Mô phỏng · Mỹ phẩm Thảo Nhi" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Đổi shop ở Tổng quan ›" })).toBeVisible();
  await page.getByTestId("ops-freshness").getByRole("button", { name: "Làm mới" }).click();
  await expect.poll(() => posts).toContain(`/v1/ops/shops/${SHOP_ID}/simulation/refresh`);
});

test("Xem như shop is read-only and never writes", async ({ page }) => {
  const { writes, seller } = await stub(page);
  await page.goto(`/ops/shops/${SHOP_ID}/xem`);
  await expect(page.getByTestId("view-as-banner")).toContainText("chỉ xem, không ghi được");
  // P22: no blanket disabled wrapper (it made every in-page control inert).
  await expect(page.getByTestId("seller-view")).not.toHaveAttribute("disabled", "");
  await expect(page.getByRole("button", { name: /Làm thay seller/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Quy tắc" }).click();
  await page.getByRole("button", { name: "Phân tích" }).click();
  expect(writes).toEqual([]);
  expect(seller).toEqual([]);
});

const VIEW_CARD = {
  id: "d1",
  title: "Tối ưu Son môi số 12",
  description: "",
  severity: "high",
  priority: 1,
  computed_at: null,
  surfaced_at: null,
  is_executable: true,
  recommendation: {
    source_kpi_ids: [],
    diagnosis: {
      version: "adr106-v1",
      as_of: "2026-10-09",
      rank: 1,
      status: "rule",
      status_label: "Theo quy tắc",
      stage: { code: "page", label: "Lượt nhấp → Đặt hàng" },
      lever: { code: "description", label: "Mô tả", action: "Viết lại mô tả" },
      main_kpi: { key: "ctor", label: "CTOR", value: "5,4 %" },
      trigger: { code: "below_median", gap: -0.3, sentence: "Thấp hơn trung vị shop" },
      channel_scope: "PRODUCT_CARD",
      recoverable_gmv_per_day: 70_000,
      product_title: "Son môi số 12",
      tiktok_product_id: "1729",
    },
    card: {
      seller_sku: "SM-012",
      seller_sku_more: 0,
      product_title: "Son môi số 12",
      workflow_label: "Tối ưu sản phẩm",
      updated_at: "2026-10-09T02:00:00Z",
      status: "pending",
      main_kpi: { key: "ctor", label: "CTOR - Thẻ sản phẩm", current: 0.054, target: 0.059, unit: "ratio" },
      expected_gmv_per_month: 2_100_000,
      reason_short: "Khách thêm giỏ rồi bỏ",
      reason_full: "Đơn/thêm giỏ của sản phẩm thấp hơn các sản phẩm tương tự trong shop.",
      tiktok_codes: ["Mô tả quá ngắn"],
      lever: { code: "description", label: "Mô tả", executor: "juli" },
      change_fields: [{ field: "description", label: "Mô tả" }],
      before_after: [{ field: "description", label: "Mô tả", before: "180 ký tự", after: "640 ký tự" }],
      gmv_method: "ước tính theo quy tắc",
    },
  },
};

test("Xem như shop: Xem thêm expands, tabs work, write buttons are disabled, links stay in view-as (P22)", async ({ page }) => {
  const { writes, seller } = await stub(page);
  await page.route(`**/v1/ops/shops/${SHOP_ID}/view/decisions`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: [VIEW_CARD] }) }),
  );
  await page.goto(`/ops/shops/${SHOP_ID}/xem`);
  const more = page.getByRole("button", { name: /Xem thêm/ }).first();
  await expect(more).toHaveAttribute("aria-expanded", "false");
  await more.click();
  await expect(page.locator(".qv-card__toggle, .qv-card__more-link").first()).toHaveAttribute("aria-expanded", "true");
  const approve = page.getByRole("button", { name: "Duyệt" }).first();
  await expect(approve).toBeDisabled();
  await expect(approve).toHaveAttribute("title", "Chế độ xem: không thể thao tác thay seller");
  await page.getByRole("tab", { name: "Đo lường" }).click();
  await expect(page.getByRole("tab", { name: "Đo lường" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "Đề xuất" }).click();
  const analysis = page.getByRole("link", { name: "Xem phân tích ›" }).first();
  await expect(analysis).toHaveAttribute("href", new RegExp(`^/ops/shops/${SHOP_ID}/xem\\?trang=phan-tich`));
  await analysis.click();
  await expect(page).toHaveURL(new RegExp(`/ops/shops/${SHOP_ID}/xem\\?trang=phan-tich`));
  await expect(page.getByTestId("view-as-banner")).toBeVisible();
  await expect(page.getByRole("button", { name: "Phân tích" })).toHaveAttribute("aria-current", "page");
  expect(writes).toEqual([]);
  expect(seller).toEqual([]);
});

test("Xem như shop shows the D29 card UI read-only (confidence, KPI range, GMV range)", async ({ page }) => {
  const { writes } = await stub(page);
  const card = {
    ...VIEW_CARD.recommendation.card,
    target_metric: "ctor",
    confidence: "medium",
    kpi: { metric: "ctor", current: 0.054, target: 0.062, target_min: 0.058, target_max: 0.066, display: "range", band_pct: 7, window_days: 30, low_data: false },
    gmv_estimate: { per_month_min: 500_000, per_month_max: 1_200_000 },
  };
  await page.route(`**/v1/ops/shops/${SHOP_ID}/view/decisions`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ data: [{ ...VIEW_CARD, recommendation: { ...VIEW_CARD.recommendation, card } }] }),
    }),
  );
  await page.goto(`/ops/shops/${SHOP_ID}/xem`);
  const view = page.getByTestId("recommendation-card").first();
  await expect(view.getByTestId("confidence-pill")).toHaveText("Độ tin cậy: Vừa");
  await expect(view).toContainText("5,8–6,6 %");
  await expect(view.getByTestId("kpi-window")).toContainText("30 ngày");
  await expect(view).toContainText("+0,5–1,2 tr ₫/tháng");
  await expect(view.getByRole("button", { name: "Duyệt" })).toBeDisabled();
  expect(writes).toEqual([]);
});

test("Mô phỏng: window, ± steps, locked cells, volatility", async ({ page }) => {
  await stub(page);
  await page.goto(`/ops/shops/${SHOP_ID}/mo-phong`);
  await expect(page.getByTestId("sim-row-product_card")).toBeVisible();
  await expect(page.getByTestId("sim-cell-seller_video-ctor")).toHaveAttribute("data-locked", "true");
  for (let k = 0; k < 5; k++) await page.getByRole("button", { name: "Tăng 1 % Thẻ sản phẩm CTOR" }).click();
  await expect(page.getByTestId("sim-cell-product_card-ctor")).toContainText("+5 %");
  await expect(page.getByTestId("sim-action").first()).toContainText("Thẻ sản phẩm · CTOR +5 %");
  await expect(page.getByTestId("vol-row").first()).toContainText("SM-012");
  await expect(page.getByRole("radio", { name: "30 ngày" })).toHaveAttribute("aria-checked", "true");
});

test("Chi phí: system limit, per-shop caps, confirm before save; banner on every page (D28.3)", async ({ page }) => {
  const { puts } = await stub(page);
  await page.goto("/ops/chi-phi");
  await expect(page.getByRole("heading", { name: "Chi phí OpenAI · tháng 10" })).toBeVisible();
  await expect(page.getByTestId("cost-used")).toHaveText("$41,00");
  await expect(page.getByTestId("cost-pct")).toHaveText("82 %");
  await expect(page.getByTestId("cost-row")).toHaveCount(2);
  await expect(page.getByTestId("cost-row").first()).toContainText("$10,00 / tháng · riêng");
  await expect(page.getByTestId("ops-cost-banner")).toContainText("Đã dùng 82 % giới hạn OpenAI");
  await page.getByRole("button", { name: "Sửa giới hạn", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Sửa giới hạn OpenAI cả hệ thống?" });
  await dialog.getByRole("button", { name: "$80" }).click();
  await expect(dialog.getByTestId("confirm-row")).toContainText("$50,00 → $80,00");
  await dialog.getByRole("button", { name: "Xác nhận lưu" }).click();
  await expect(page.getByTestId("ops-toast")).toContainText("Đã lưu giới hạn · ghi 1 dòng nhật ký");
  await page.getByRole("button", { name: "Sửa giới hạn Mỹ phẩm Thảo Nhi" }).click();
  const shopDialog = page.getByRole("dialog", { name: "Sửa giới hạn riêng của Mỹ phẩm Thảo Nhi?" });
  await shopDialog.getByRole("button", { name: "$20" }).click();
  await shopDialog.getByRole("button", { name: "Xác nhận lưu" }).click();
  await expect.poll(() => puts).toEqual([{ usd: 80 }, { usd: 20 }]);
  // The banner is on every Ops page (one call, cached).
  await page.getByRole("navigation", { name: "Ops" }).getByRole("link", { name: "Nhật ký" }).click();
  await expect(page.getByTestId("ops-cost-banner")).toBeVisible();
});

test("Thời hạn: sorted rows, filters, history, extend by package with a contract number (D28.4)", async ({ page }) => {
  const { puts } = await stub(page);
  await page.goto("/ops/thoi-han");
  await expect(page.getByRole("heading", { name: "Thời hạn" })).toBeVisible();
  await expect(page.getByTestId("term-row")).toHaveCount(6);
  await expect(page.getByTestId("term-pill").first()).toHaveText("Chỉ xem");
  await page.getByRole("group", { name: "Lọc theo thời hạn" }).getByRole("button", { name: "Ân hạn" }).click();
  await expect(page.getByTestId("term-row")).toHaveCount(1);
  await page.getByRole("button", { name: "Mẹ Bông Kids", exact: true }).click();
  await expect(page.getByTestId("term-period")).toContainText("HĐ-2026-008 · thien.phung");
  await expect(page.getByTestId("term-seller-sees")).toContainText("Juli vẫn chạy thêm 4 ngày");
  await page.getByRole("button", { name: "Gói 365 ngày cho Mẹ Bông Kids" }).click();
  const dialog = page.getByRole("dialog", { name: "Gia hạn Mẹ Bông Kids?" });
  await expect(dialog).toContainText("Nguồn: Hợp đồng");
  await expect(dialog).toContainText("Shop đã hết hạn: kỳ mới tính từ hôm nay.");
  await expect(dialog.getByRole("button", { name: "Gia hạn" })).toBeDisabled();
  await dialog.getByLabel("Số hợp đồng").fill("HĐ-2026-014");
  await dialog.getByRole("button", { name: "Gia hạn" }).click();
  await expect(page.getByTestId("ops-toast")).toContainText("Đã gia hạn Mẹ Bông Kids");
  expect(puts).toEqual([{ days: 365, reference: "HĐ-2026-014" }]);
});

test("Xem như shop shows the seller's term strip", async ({ page }) => {
  await stub(page);
  await page.goto(`/ops/shops/${SHOP_ID}/xem`);
  await expect(page.getByTestId("term-strip")).toContainText("Gói Juli của shop đã hết hạn ngày 09/10/2026");
});
