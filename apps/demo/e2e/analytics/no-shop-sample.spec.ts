import { expect, test, type Page } from "@playwright/test";

import { HOME_MATRIX_REGION, enterReplayDemo } from "../helpers/demo-navigation";

/**
 * P13 (owner, 2026-10-10): signed in with no TikTok Shop connected, Trang chủ,
 * Phân tích and Quyết định show the bundled sample (the cosmetics shop) under
 * "Bạn đang xem dữ liệu mẫu · Kết nối TikTok Shop ›" — no /v1 request for the
 * sample; Home's sample agrees with Phân tích's; the Phân tích header sits on
 * the left.
 */

function trackApi(page: Page): string[] {
  const urls: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/v1/")) urls.push(`${url.pathname}${url.search}`);
  });
  return urls;
}

async function signInWithoutShop(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
    window.localStorage.removeItem("juli_demo_active_shop");
  });
}

async function expectStrip(page: Page) {
  const strip = page.getByTestId("no-shop-sample-strip");
  await expect(strip).toHaveText("Bạn đang xem dữ liệu mẫu · Kết nối TikTok Shop ›");
  await expect(strip.getByRole("link", { name: "Kết nối TikTok Shop ›" })).toHaveAttribute("href", "/auth/connect-shop");
}

test.describe("signed in, no TikTok Shop → the sample under the connect strip", () => {
  test("Trang chủ, Phân tích, Quyết định: the sample with the strip, no /v1 request", async ({ page }) => {
    await signInWithoutShop(page);
    const api = trackApi(page);

    await page.goto("/");
    await expectStrip(page);
    await expect(page.getByRole("region", { name: HOME_MATRIX_REGION })).toBeVisible();
    await expect(page.getByTestId("mock-data-notice")).toContainText("Cửa hàng Mẫu Hoa Mai");
    await expect(page.getByText(/Bạn chưa chọn shop/)).toHaveCount(0);

    await page.getByRole("region", { name: HOME_MATRIX_REGION }).getByRole("link", { name: /^CTOR Thẻ sản phẩm:/ }).click();
    await expect(page).toHaveURL(/\/analytics\?tab=san-pham&stream=the-san-pham&metric=ctor$/);
    await expectStrip(page);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^Thẻ sản phẩm: CTOR giảm \d+ %$/);
    await expect(page.getByTestId("ranking-table")).toBeVisible();

    await page.goto("/decisions");
    await expectStrip(page);
    await expect(page.locator('[data-decision-id="sample-sm-012"]')).toBeVisible();
    await expect(page.getByTestId("mock-data-notice")).toContainText("Cửa hàng Mẫu Hoa Mai");

    expect(api).toEqual([]);
  });

  test("the strip's link opens Kết nối TikTok Shop", async ({ page }) => {
    await signInWithoutShop(page);
    await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: '{"data":[]}' }));
    await page.goto("/analytics");
    await page.getByTestId("no-shop-sample-strip").getByRole("link", { name: "Kết nối TikTok Shop ›" }).click();
    await expect(page).toHaveURL(/\/auth\/connect-shop$/);
  });

  test("the Phân tích header (kicker + h1) is left-aligned", async ({ page }) => {
    await signInWithoutShop(page);
    await page.goto("/analytics");
    const section = page.locator(".pa-page");
    await expect(section.locator(".pa-title")).toBeVisible();
    const box = (await section.boundingBox())!;
    for (const el of [section.locator(".pa-eyebrow"), section.locator(".pa-title")]) {
      const b = (await el.boundingBox())!;
      expect(Math.abs(b.x - box.x)).toBeLessThanOrEqual(2);
    }
  });
});

test("signed in with a shop, no report yet: the Phân tích header is left-aligned too", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
    window.localStorage.setItem("juli_demo_active_shop", JSON.stringify({ id: "shop-e2e", name: "Shop E2E" }));
  });
  await page.route("**/v1/**", (route) => route.fulfill({ status: 404, contentType: "application/json", body: '{"detail":"none"}' }));
  await page.goto("/analytics");
  await expect(page.getByText("Chưa có báo cáo")).toBeVisible();
  await expect(page.getByTestId("no-shop-sample-strip")).toHaveCount(0);
  const section = page.locator(".pa-page");
  const box = (await section.boundingBox())!;
  for (const el of [section.locator(".eyebrow"), section.getByRole("heading", { level: 1, name: "Phân tích luồng truy cập" })]) {
    const b = (await el.boundingBox())!;
    expect(Math.abs(b.x - box.x)).toBeLessThanOrEqual(2);
  }
});

test("Trang chủ's sample reads the same CTOR as Phân tích's (5,14 %)", async ({ page }) => {
  const api = trackApi(page);
  await enterReplayDemo(page);
  const cell = page.getByRole("region", { name: HOME_MATRIX_REGION }).getByRole("link", { name: /^CTOR Thẻ sản phẩm:/ });
  await expect(cell).toContainText("5,14 %");
  await expect(page.getByTestId("mock-data-notice")).toContainText("Cửa hàng Mẫu Hoa Mai");
  await expect(page.getByTestId("shop-header")).toContainText("Cửa hàng Mẫu Hoa Mai");
  await cell.click();
  await expect(page.getByRole("button", { name: /^CTOR · Thẻ sản phẩm/ })).toContainText("5,14 %");
  expect(api).toEqual([]);
});
