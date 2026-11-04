import { expect, test, type Page } from "@playwright/test";

import { critical, matrix, overview, ranking } from "../../src/lib/shopee-analytics/__tests__/fixtures";
import { REPORT, ROWS, reportOf } from "../../src/lib/shopee-kol/__tests__/fixtures";

/**
 * P91 Phân tích › KOL in a browser, API stubbed with the backend's real answer (`kol.table`),
 * synthetic data only: the table with its server totals, a channel filter that goes to the
 * server as `channel=`, and no horizontal page scroll on a phone.
 */

const SHOP = { id: "shop-shopee-e2e", name: "Shop gia dụng" };

async function stub(page: Page) {
  const asked: string[] = [];
  await page.addInitScript((shop) => {
    window.sessionStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
    window.sessionStorage.setItem("juli_demo_active_shop", JSON.stringify(shop));
  }, SHOP);
  await page.route("**/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname === "/v1/shops/me") return json({ id: SHOP.id, platform: "shopee" });
    if (url.pathname.endsWith("/shopee/kols")) {
      asked.push(url.search);
      const channel = url.searchParams.get("channel");
      return json(channel ? reportOf(ROWS, { channel }) : REPORT);
    }
    if (url.pathname.endsWith("/shopee/overview")) return json(overview());
    if (url.pathname.endsWith("/shopee/matrix")) return json(matrix());
    if (url.pathname.endsWith("/shopee/critical")) return json(critical());
    if (url.pathname.endsWith("/shopee/ranking")) return json(ranking());
    return json({ detail: "none" }, 404);
  });
  return asked;
}

test.describe("seller: Phân tích › KOL", () => {
  test("rows, server totals, and the channel filter asks the server", async ({ page }) => {
    const asked = await stub(page);
    await page.goto("/phan-tich?tab=kol");
    await expect(page.getByTestId("kol-table")).toBeVisible();
    await expect(page.getByTestId("kol-tiles")).toContainText("ROI gồm mẫu");
    await expect(page.locator("[data-testid^=kol-row-]")).toHaveCount(ROWS.length);
    await page.getByRole("button", { name: "Facebook" }).click();
    await expect.poll(() => asked.some((q) => q.includes("channel=Facebook"))).toBe(true);
    await expect(page.locator("[data-testid^=kol-row-]")).toHaveCount(ROWS.filter((r) => r.channel === "Facebook").length);
  });
});

test.describe("phone: Phân tích › KOL", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("the wide table scrolls inside itself, not the page", async ({ page }) => {
    await stub(page);
    await page.goto("/phan-tich?tab=kol");
    await expect(page.getByTestId("kol-table")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  });
});
