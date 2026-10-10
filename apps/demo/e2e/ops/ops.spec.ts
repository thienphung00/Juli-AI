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

async function stub(page: Page) {
  const writes: string[] = [];
  const seller: string[] = [];
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
    if (path === "/v1/ops/me") return json(ME);
    if (path === "/v1/ops/overview") return json(OVERVIEW);
    if (path === `/v1/ops/shops/${SHOP_ID}/settings`) return json(SETTINGS);
    if (path === `/v1/ops/shops/${SHOP_ID}/view-session`) return json(VIEW_SESSION);
    if (path === `/v1/ops/shops/${SHOP_ID}/view/decisions`) return json({ data: [] });
    if (path === `/v1/ops/shops/${SHOP_ID}/view/runs`) return json({ data: [] });
    if (path === `/v1/ops/shops/${SHOP_ID}/simulation`) return json(SIMULATION);
    if (path === `/v1/ops/shops/${SHOP_ID}/rules`) return json({ data: RULES });
    return json({ detail: "not stubbed" }, 404);
  });
  return { writes, seller };
}

test("Tổng quan lists shops with totals and the Admin-only Huỷ kết nối", async ({ page }) => {
  const { seller } = await stub(page);
  await page.goto("/ops");
  await expect(page.getByRole("heading", { name: "Gian hàng đã kết nối" })).toBeVisible();
  await expect(page.getByTestId("ops-shop-row")).toHaveCount(3);
  await expect(page.getByTestId("cap-badge")).toContainText("Chạm giới hạn");
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
  await expect(page.getByRole("heading", { name: "Mỹ phẩm Thảo Nhi" })).toBeVisible();
  await expect(page.getByTestId("ops-setting")).toHaveCount(7);
  await expect(page.getByText("Ghi đè")).toBeVisible();
  await expect(page.getByRole("button", { name: "Mời seller" })).toBeVisible();
  await expect(page.getByTestId("ops-audit-row")).toHaveCount(1);
  await expect(page.getByTestId("ops-rules").getByTestId("rules-editor")).toBeVisible();
  await expect(page.getByTestId("rule-content_tone")).toBeVisible();
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
