import { expect, test, type Page } from "@playwright/test";

import { ME, OVERVIEW, SETTINGS, SHOP_ID, SIMULATION, VIEW_SESSION } from "../../src/components/ops/__tests__/fixtures";

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
  await expect(page.getByTestId("seller-view")).toHaveAttribute("disabled", "");
  await expect(page.getByRole("button", { name: /Làm thay seller/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Quy tắc" }).click();
  await page.getByRole("button", { name: "Phân tích" }).click();
  expect(writes).toEqual([]);
  expect(seller).toEqual([]);
});

test("Mô phỏng: window, ± steps, locked cells, volatility", async ({ page }) => {
  await stub(page);
  await page.goto(`/ops/shops/${SHOP_ID}/mo-phong`);
  await expect(page.getByTestId("sim-row-product_card")).toBeVisible();
  await expect(page.getByTestId("sim-cell-seller_video-ctor")).toHaveAttribute("data-locked", "true");
  await page.getByRole("button", { name: "Tăng 5 % Thẻ sản phẩm CTOR" }).click();
  await expect(page.getByTestId("sim-cell-product_card-ctor")).toContainText("+5 %");
  await expect(page.getByTestId("sim-action").first()).toContainText("Thẻ sản phẩm · CTOR +5 %");
  await expect(page.getByTestId("vol-row").first()).toContainText("SM-012");
  await expect(page.getByRole("radio", { name: "30 ngày" })).toHaveAttribute("aria-checked", "true");
});
