import { expect, test } from "@playwright/test";

import { detailOf, summaryOf, versionedVoucher, voucherCardB } from "../../src/lib/shopee-decisions/__tests__/fixtures";
import { overview } from "../../src/lib/shopee-analytics/__tests__/fixtures";

/**
 * P90 step 9b / P91 smoke: /decisions of a Shopee shop in a browser, API stubbed with synthetic cards.
 * Quyết định shows one card per product, the card page lists its versions and recomputes the chosen
 * one through the what-if endpoint (with `version`), and approving posts `chosen_version`. Nothing else
 * leaves for a seller write.
 */

const SHOP = { id: "shop-shopee-e2e", name: "Shop gia dụng" };

test("Shopee /decisions: list -> card -> what-if -> approve", async ({ page }) => {
  const posts: string[] = [];
  const bodies: unknown[] = [];
  await page.addInitScript((shop) => {
    window.sessionStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
    window.sessionStorage.setItem("juli_demo_active_shop", JSON.stringify(shop));
  }, SHOP);
  await page.route("**/v1/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (req.method() === "POST") posts.push(path);
    if (path === "/v1/shops/me") return json({ id: SHOP.id, platform: "shopee" });
    if (path.endsWith("/recommendations")) return json({ platform: "shopee", xep_theo: "diem", queue: "all", cards: [summaryOf(versionedVoucher())], counts: { family: { voucher: 1 }, section: { aov: 1 }, total: 1 } });
    if (path.endsWith("/whatif")) return json({ card: { ...versionedVoucher(), ...voucherCardB() } });
    if (path.endsWith("/approve")) {
      bodies.push(req.postDataJSON());
      return json({ id: "card-voucher", status: "approved", approval_id: "a1", chosen_version: 2 });
    }
    if (path.includes("/recommendations/")) return json(detailOf(versionedVoucher(), { code: "JC-2611-0007", product_id: "BEP-S5", product_queue: 1 }));
    if (path.startsWith("/v1/demo/shopee/")) return json(overview());
    return json({ detail: "none" }, 404);
  });
  await page.goto("/decisions");
  await expect(page.getByTestId("sq-card-card-voucher")).toBeVisible();
  await expect(page.getByText("Shopee", { exact: true }).first()).toBeVisible();
  await page.getByRole("link", { name: "Mở thẻ để chọn phiên bản" }).click();
  await expect(page.getByTestId("sv-count")).toHaveText("3 phiên bản của cùng một thay đổi");
  await page.getByTestId("sv-ver-2").click();
  await page.getByRole("slider", { name: "Đơn tối thiểu" }).fill("200000");
  await expect(page.getByTestId("sd-sure-bien")).toContainText("23,4%");
  await page.getByRole("button", { name: "Duyệt V2" }).click();
  await expect.poll(() => posts.some((p) => p.endsWith("/approve"))).toBe(true);
  expect(bodies[0]).toMatchObject({ chosen_version: 2, acknowledge_breaches: false });
  expect(posts.every((p) => p.includes("/recommendations/"))).toBe(true);
});
