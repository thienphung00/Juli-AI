import { expect, test, type Page } from "@playwright/test";

import { ME, SETTINGS, SHOP_ID, VIEW_SESSION } from "../../src/components/ops/__tests__/fixtures";
import { matrix, product } from "../../src/lib/shopee-analytics/__tests__/fixtures";
import { compareResult, detailOf, manualResult, summaryOf, titleCard, versionedVoucher } from "../../src/lib/shopee-decisions/__tests__/fixtures";

/**
 * P91 smoke (wave 3): the versioned card with its breach warning, the product's Đề xuất tab, Tự tạo /
 * So sánh phương án, and the Ops list with the card-by-code lookup, in a browser with the API stubbed
 * by the synthetic fixtures. Synthetic data only.
 */

const SHOP = { id: "shop-shopee-e2e", name: "Shop gia dụng" };

async function stub(page: Page) {
  const posts: { path: string; body: unknown }[] = [];
  await page.addInitScript((shop) => {
    window.sessionStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
    window.sessionStorage.setItem("juli_demo_active_shop", JSON.stringify(shop));
  }, SHOP);
  await page.route("**/v1/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (req.method() === "POST") posts.push({ path, body: req.postDataJSON() });
    if (path === "/v1/shops/me") return json({ id: SHOP.id, platform: "shopee" });
    if (path.endsWith("/shopee/matrix")) return json(matrix());
    if (path.includes("/shopee/products/")) return json(product());
    if (path.endsWith("/compare")) return json(compareResult(3));
    if (path.endsWith("/manual")) return json(manualResult(), 201);
    if (path.endsWith("/approve")) return json({ id: "card-voucher", status: "approved", approval_id: "a1", chosen_version: 3 });
    if (path.endsWith("/recommendations")) {
      const cards = [summaryOf(versionedVoucher(), { code: "JC-2611-0007", product_queue: 1 }), summaryOf(titleCard(), { code: "JC-2611-0011", product_queue: 2 })];
      return json({ platform: "shopee", xep_theo: "diem", queue: "product", cards, counts: { family: {}, section: {}, total: cards.length } });
    }
    if (path.includes("/recommendations/")) return json(detailOf(versionedVoucher(), { code: "JC-2611-0007", product_id: "BEP-S5", product_queue: 1 }));
    return json({ detail: "none" }, 404);
  });
  return posts;
}

test.describe("seller: P91", () => {
  test("a version that breaks the floor: warning, Quay lại, Vẫn tiếp tục -> approve with acknowledge_breaches", async ({ page }) => {
    const posts = await stub(page);
    await page.goto("/decisions?the=card-voucher");
    await page.getByTestId("sv-ver-3").click();
    await expect(page.getByTestId("sd-approve-hint")).toContainText("V3 chạm giá sàn: vẫn duyệt được, Juli sẽ hiện cảnh báo trước.");
    await page.getByRole("button", { name: "Duyệt V3" }).click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("Duyệt V3 dù chạm giá sàn?");
    await dialog.getByRole("button", { name: "Quay lại" }).click();
    expect(posts.some((p) => p.path.endsWith("/approve"))).toBe(false);
    await page.getByRole("button", { name: "Duyệt V3" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Vẫn tiếp tục" }).click();
    await expect.poll(() => posts.find((p) => p.path.endsWith("/approve"))?.body).toMatchObject({ chosen_version: 3, acknowledge_breaches: true });
    await expect(page.getByTestId("sd-ack")).toContainText("Đã xác nhận vượt giá sàn");
  });

  test("Sản phẩm › Đề xuất lists the queue; 'Tự tạo phương án' compares and saves", async ({ page }) => {
    const posts = await stub(page);
    await page.goto("/san-pham/BEP-S5?tab=dx");
    await expect(page.getByTestId("sp-proposals")).toBeVisible();
    await expect(page.getByTestId("sp-card-card-voucher")).toContainText("#1 · Đang ở Quyết định");
    await page.getByTestId("sp-builder").click();
    await expect(page.getByRole("heading", { name: "Tự đặt ưu đãi, xem số trước khi quyết định" })).toBeVisible();
    await expect(page.getByTestId("sb-table")).toBeVisible();
    await page.getByRole("button", { name: "+ Thêm phương án" }).click();
    await page.getByRole("button", { name: "+ Thêm phương án" }).click();
    await expect(page.getByTestId("sb-floor-3")).toContainText("✕");
    await page.getByRole("radio", { name: /P3 \(chạm giá sàn\)/ }).click();
    await page.getByTestId("sb-save-btn").click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Vẫn tiếp tục" }).click();
    await expect(page.getByTestId("sb-saved")).toContainText("Đã lưu");
    expect(posts.find((p) => p.path.endsWith("/manual"))?.body).toMatchObject({ chosen: 2, acknowledge_breaches: true });
  });
});

test.describe("phone: Tự tạo phương án", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("compares as swipe cards without a horizontal page scroll", async ({ page }) => {
    await stub(page);
    await page.goto("/decisions?tu-tao=1&from=quyet-dinh");
    await expect(page.getByTestId("sb-swipe")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  });
});

test.describe("Juli Ops: Đề xuất", () => {
  test("list with codes, search by code, builder link, no export button", async ({ page }) => {
    await page.addInitScript(() => {
      window.localStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
    });
    await page.route("**/v1/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
      if (path === "/v1/ops/me") return json(ME);
      if (path.endsWith("/shopee/analytics/matrix")) return json(matrix());
      if (path.endsWith("/shopee/recommendations")) {
        const cards = [summaryOf(versionedVoucher(), { code: "JC-2611-0007", product_queue: 1 }), summaryOf(titleCard(), { code: "JC-2611-0011", product_queue: 2, origin: "manual" })];
        return json({ platform: "shopee", xep_theo: "diem", queue: "all", cards, counts: { family: {}, section: {}, total: 2 } });
      }
      if (path === `/v1/ops/shops/${SHOP_ID}/view-session`) return json({ ...VIEW_SESSION, shop: { ...SETTINGS.shop, platform: "shopee" } });
      return json({ detail: "none" }, 404);
    });
    await page.goto(`/ops/shops/${SHOP_ID}/shopee/de-xuat`);
    await expect(page.getByTestId("ops-row-JC-2611-0007")).toBeVisible();
    await expect(page.getByTestId("ops-row-JC-2611-0011")).toContainText("Thủ công");
    await page.getByPlaceholder("JC-2611-0007").fill("0011");
    await expect(page.getByTestId("ops-row-JC-2611-0007")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "+ Tạo phương án thủ công" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Excel|Export|Xuất file/i })).toHaveCount(0);
  });
});
