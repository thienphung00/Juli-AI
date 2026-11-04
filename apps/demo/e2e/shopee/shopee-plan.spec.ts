import { expect, test, type Page } from "@playwright/test";

import { matrix } from "../../src/lib/shopee-analytics/__tests__/fixtures";
import { confirmedPlan, plan, stackedPlan } from "../../src/lib/shopee-decisions/__tests__/plan-fixtures";
import { summaryOf, versionedVoucher } from "../../src/lib/shopee-decisions/__tests__/fixtures";

/**
 * P91 Kế hoạch in a browser, API stubbed with the backend's real answer shapes
 * (`plans.get_plan`, synthetic data only): the draft with its aggregate and window, the
 * acknowledged confirm, and no horizontal page scroll on a phone.
 */

const SHOP = { id: "shop-shopee-e2e", name: "Shop gia dụng" };

async function stub(page: Page, first = plan()) {
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
    if (path.endsWith("/recommendations/plan")) return json(first);
    if (path.endsWith("/recommendations/plan/confirm")) return json({ ...confirmedPlan(), aggregate: first.aggregate });
    if (path.endsWith("/recommendations/plan/window")) return json(first);
    if (path.endsWith("/recommendations")) {
      const cards = [summaryOf(versionedVoucher(), { code: "JC-2611-0009", product_queue: 1 })];
      return json({ platform: "shopee", xep_theo: "diem", queue: "all", cards, counts: { family: {}, section: {}, total: 1 } });
    }
    return json({ detail: "none" }, 404);
  });
  return posts;
}

test.describe("seller: Kế hoạch", () => {
  test("the draft: cards, the plan's table, the window; confirm with the second yes sends acknowledge_breaches", async ({ page }) => {
    const posts = await stub(page, stackedPlan());
    await page.goto("/decisions?ke-hoach=1");
    await expect(page.getByTestId("kh-count")).toContainText("3 thẻ · 2 sản phẩm");
    await expect(page.getByTestId("kh-agg-floor")).toContainText("✕");
    await expect(page.getByTestId("kh-win")).toBeVisible();
    await page.getByTestId("kh-win").getByRole("radio", { name: /7 ngày cho cả kế hoạch/ }).click();
    await expect.poll(() => posts.find((p) => p.path.endsWith("/plan/window"))?.body).toEqual({ days: 7 });
    await page.getByTestId("kh-confirm").click();
    await page.getByRole("dialog").getByRole("button", { name: "Vẫn tiếp tục" }).click();
    await expect.poll(() => posts.find((p) => p.path.endsWith("/plan/confirm"))?.body).toEqual({ acknowledge_breaches: true });
    await expect(page.getByTestId("kh-done")).toContainText("Đã xác nhận kế hoạch KH-2611-003");
  });
});

test.describe("phone: Kế hoạch", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("fits the screen without a horizontal page scroll", async ({ page }) => {
    await stub(page);
    await page.goto("/decisions?ke-hoach=1");
    await expect(page.getByTestId("kh-plan")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  });
});
