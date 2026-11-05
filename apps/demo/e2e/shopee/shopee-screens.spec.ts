import { expect, test, type Page } from "@playwright/test";

import { ME, SETTINGS, SHOP_ID, VIEW_SESSION } from "../../src/components/ops/__tests__/fixtures";
import { critical, matrix, overview, product, ranking } from "../../src/lib/shopee-analytics/__tests__/fixtures";

/**
 * P90 step 9 smoke: the Shopee shop screens end to end in a browser, with the API stubbed by the
 * synthetic fixtures. The main routes render, the artboards' links land on the right screen with
 * the right parameters (VERIFY.md table), a TikTok shop keeps today's navigation, and Juli Ops
 * reads the same screens through the Ops API. No request ever leaves for a seller write.
 */

const SHOP = { id: "shop-shopee-e2e", name: "Shop gia dụng" };

async function stubSeller(page: Page, opts: { shopee: boolean }) {
  const seen: string[] = [];
  await page.addInitScript((shop) => {
    window.sessionStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
    window.sessionStorage.setItem("juli_demo_active_shop", JSON.stringify(shop));
  }, SHOP);
  await page.route("**/v1/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    seen.push(`${req.method()} ${path}`);
    if (path.startsWith("/v1/demo/shopee/")) {
      if (!opts.shopee) return json({ detail: { code: "not_a_shopee_shop", message: "x" } }, 409);
      if (path.endsWith("/overview")) return json(overview());
      if (path.endsWith("/matrix")) return json(matrix());
      if (path.endsWith("/critical")) return json(critical());
      if (path.endsWith("/ranking")) return json(ranking());
      if (path.includes("/products/")) return json(product());
    }
    return json({ detail: "none" }, 404);
  });
  return seen;
}

test.describe("seller: Shopee shop", () => {
  test("Tổng quan renders with the Shopee navigation", async ({ page }) => {
    await stubSeller(page, { shopee: true });
    await page.goto("/tong-quan");
    await expect(page.getByTestId("sa-tile-gmv")).toContainText("50.000.000đ");
    const nav = page.getByRole("navigation", { name: "Điều hướng chính" });
    await expect(nav.getByRole("link")).toHaveText(["Tổng quan", "Phân tích", "Sản phẩm", "Quyết định", "Từ khóa", "Quảng cáo", "Đơn hàng", "Luồng"]);
    await expect(nav.getByRole("link", { name: "Tổng quan" })).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("sa-five")).toContainText("② Doanh thu thêm / chi thêm");
    await expect(page.getByTestId("sa-flow-total")).toContainText("50.000.000đ");
    await expect(page.getByTestId("sa-profit")).toContainText("trên 99,4% doanh thu có giá vốn");
    await expect(page.getByTestId("sa-mrow-BEP-S5")).toBeVisible();
    // The page never needs a horizontal scroll, desktop or phone.
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  });

  test("KPI tile → Xếp hạng → Mở sản phẩm → back to the highlighted row", async ({ page }) => {
    await stubSeller(page, { shopee: true });
    await page.goto("/tong-quan");
    await page.getByTestId("sa-tile-ctr").click();
    await expect(page).toHaveURL(/\/xep-hang\?kpi=ctr&src=all&from=tong-quan$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Xếp hạng CTR · Tất cả");
    const row = page.getByTestId("sa-rk-row-XM-003");
    await row.getByRole("button", { name: /Xơ mướp rửa chén/ }).click();
    await row.getByRole("link", { name: /Mở sản phẩm/ }).click();
    await expect(page).toHaveURL(/\/san-pham\/XM-003\?tab=ng&kpi=ctr&src=all&row=XM-003&from=ranking$/);
    await expect(page.getByTestId("sa-from-banner")).toContainText("Mở từ Xếp hạng · CTR × Tất cả · dòng XM-003");
    await page.getByRole("link", { name: "‹ Xếp hạng" }).click();
    await expect(page).toHaveURL(/\/xep-hang\?kpi=ctr&src=all&focus=XM-003$/);
    await expect(page.getByTestId("sa-rk-row-XM-003")).toContainText("Vừa xem ở thẻ");
  });

  test("Phân tích → Xem xếp hạng lands on the row with from=phan-tich", async ({ page }) => {
    await stubSeller(page, { shopee: true });
    await page.goto("/phan-tich");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("3 chỉ số cần chú ý");
    await page.getByTestId("sa-item-product:GL-001:bien").getByRole("link", { name: "Xem xếp hạng ›" }).click();
    await expect(page).toHaveURL(/\/xep-hang\?kpi=bien&src=all&focus=GL-001&from=phan-tich$/);
    await expect(page.getByRole("link", { name: "‹ Phân tích" })).toBeVisible();
  });

  test("Sản phẩm: header, five numbers and the five tabs", async ({ page }) => {
    await stubSeller(page, { shopee: true });
    await page.goto("/san-pham/BEP-S5?tab=ng");
    await expect(page.getByTestId("sa-title")).toContainText("Bộ vệ sinh bếp 5 món");
    await expect(page.getByTestId("sa-floor-op")).toContainText("181.979đ");
    await expect(page.getByTestId("sa-tab-ng")).toBeVisible();
    for (const [name, testId] of [
      ["Từ khoá", "sa-tab-kw"],
      ["Chi phí & giá sàn", "sa-tab-cp"],
      ["Lịch sử", "sa-tab-ls"],
      ["Hiệu suất", "sa-tab-hs"],
    ] as const) {
      await page.getByRole("tablist", { name: "Sản phẩm" }).getByRole("link", { name }).click();
      await expect(page.getByTestId(testId)).toBeVisible();
    }
    await expect(page.getByTestId("sa-tab-hs")).toBeVisible();
  });

  test("a card chip opens Quyết định on the card", async ({ page }) => {
    await stubSeller(page, { shopee: true });
    await page.goto("/tong-quan");
    await page.getByTestId("sa-mrow-BEP-S5").getByRole("link", { name: /→/ }).click();
    await expect(page).toHaveURL(/\/decisions\?the=c_bep_voucher&from=tong-quan$/);
  });

  test("a TikTok shop keeps Trang chủ / Quyết định / Phân tích / Juli", async ({ page }) => {
    await stubSeller(page, { shopee: false });
    await page.goto("/decisions");
    const nav = page.getByRole("navigation", { name: "Điều hướng chính" });
    await expect(nav.getByRole("link")).toHaveText([/^Trang chủ/, /^Quyết định/, /^Phân tích/, /^Juli/]);
  });

  test("no request is anything but a GET to the Shopee read API", async ({ page }) => {
    const seen = await stubSeller(page, { shopee: true });
    await page.goto("/tong-quan");
    await expect(page.getByTestId("sa-tile-gmv")).toBeVisible();
    expect(seen.filter((s) => s.includes("/v1/demo/shopee/")).every((s) => s.startsWith("GET "))).toBe(true);
  });
});

test.describe("Juli Ops: Shopee shop", () => {
  const SHOPEE_SESSION = { ...VIEW_SESSION, shop: { ...SETTINGS.shop, platform: "shopee" } };

  async function stubOps(page: Page) {
    const seen: string[] = [];
    await page.addInitScript(() => {
      window.localStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
    });
    await page.route("**/v1/**", async (route) => {
      const req = route.request();
      const path = new URL(req.url()).pathname;
      const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
      seen.push(`${req.method()} ${path}`);
      const base = `/v1/ops/shops/${SHOP_ID}`;
      if (path === "/v1/ops/me") return json(ME);
      if (path === `${base}/view-session`) return json(SHOPEE_SESSION);
      if (path === `${base}/shopee/analytics/overview`) return json(overview());
      if (path === `${base}/shopee/analytics/matrix`) return json(matrix());
      if (path === `${base}/shopee/analytics/critical`) return json(critical());
      if (path === `${base}/shopee/analytics/ranking`) return json(ranking());
      if (path.startsWith(`${base}/shopee/analytics/products/`)) return json(product());
      return json({ detail: "none" }, 404);
    });
    return seen;
  }

  test("Xem như shop opens on Tổng quan and its links stay in view-as", async ({ page }) => {
    const seen = await stubOps(page);
    await page.goto(`/ops/shops/${SHOP_ID}/xem`);
    await expect(page.getByTestId("sa-tile-gmv")).toContainText("50.000.000đ");
    await expect(page.getByTestId("view-as-banner")).toContainText("chỉ xem");
    await page.getByTestId("sa-tile-ctr").click();
    await expect(page).toHaveURL(new RegExp(`/ops/shops/${SHOP_ID}/xem\\?trang=xep-hang&kpi=ctr&src=all&from=tong-quan$`));
    await expect(page.getByTestId("sa-ranking")).toBeVisible();
    expect(seen.some((s) => s.startsWith("GET /v1/demo"))).toBe(false);
    expect(seen.filter((s) => s.includes("/shopee/analytics/")).every((s) => s.startsWith("GET "))).toBe(true);
  });

  test("the Ops analytics tab shows the four screens", async ({ page }) => {
    await stubOps(page);
    await page.goto(`/ops/shops/${SHOP_ID}/shopee/phan-tich`);
    await expect(page.getByTestId("sa-tile-gmv")).toBeVisible();
    await page.getByTestId("sa-screen-tabs").getByRole("link", { name: "Phân tích" }).click();
    await expect(page).toHaveURL(new RegExp(`man=phan-tich`));
    await expect(page.getByTestId("sa-phan-tich")).toBeVisible();
  });
});
