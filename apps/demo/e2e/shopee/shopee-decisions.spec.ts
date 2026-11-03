import { expect, test } from "@playwright/test";

import { detailOf, summaryOf, voucherCard, voucherCardB } from "../../src/lib/shopee-decisions/__tests__/fixtures";
import { overview } from "../../src/lib/shopee-analytics/__tests__/fixtures";

/**
 * P90 step 9b smoke: /decisions of a Shopee shop in a browser, API stubbed with synthetic cards.
 * The list shows the family section, the card page recomputes through the what-if endpoint, and
 * approving posts the approve call. Nothing else leaves for a seller write.
 */

const SHOP = { id: "shop-shopee-e2e", name: "Shop gia dụng" };

test("Shopee /decisions: list -> card -> what-if -> approve", async ({ page }) => {
  const posts: string[] = [];
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
    if (path.endsWith("/recommendations")) return json({ platform: "shopee", xep_theo: "diem", cards: [summaryOf(voucherCard())], counts: { family: { voucher: 1 }, section: { aov: 1 }, total: 1 } });
    if (path.endsWith("/whatif")) return json({ card: voucherCardB() });
    if (path.endsWith("/approve")) return json({ id: "card-voucher", status: "approved", approval_id: "a1" });
    if (path.includes("/recommendations/")) return json(detailOf(voucherCard()));
    if (path.startsWith("/v1/demo/shopee/")) return json(overview());
    return json({ detail: "none" }, 404);
  });
  await page.goto("/decisions");
  await expect(page.getByTestId("sd-section-voucher")).toBeVisible();
  await expect(page.getByText("Shopee", { exact: true }).first()).toBeVisible();
  await page.getByRole("link", { name: /Voucher đơn tối thiểu/ }).click();
  await expect(page.getByTestId("sd-sure-eff")).toContainText("Hoà vốn khi thêm ≥ 3 đơn");
  await page.getByRole("slider", { name: "Đơn tối thiểu" }).fill("200000");
  await expect(page.getByTestId("sd-sure-bien")).toContainText("23,4%");
  await page.getByRole("button", { name: /Phê duyệt/ }).click();
  await expect.poll(() => posts.some((p) => p.endsWith("/approve"))).toBe(true);
  expect(posts.every((p) => p.includes("/recommendations/"))).toBe(true);
});
