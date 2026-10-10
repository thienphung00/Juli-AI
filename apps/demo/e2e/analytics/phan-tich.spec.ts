import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { HOME_MATRIX_REGION, enterReplayDemo, expectFourDestinationShell } from "../helpers/demo-navigation";

/**
 * Phân tích (ADR-109 Amendment 2, AC-12.x) end to end: the signed-out
 * "Bản minh họa" (the Quyết định sample's shop, bundled — no /v1 request),
 * the two-way links with Đề xuất, and a stubbed signed-in seller.
 */

const SM012 = "1729000012";

function trackApi(page: Page): string[] {
  const urls: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/v1/")) urls.push(`${url.pathname}${url.search}`);
  });
  return urls;
}

const row = (page: Page, name: string) => page.getByTestId("pa-row").filter({ hasText: name });

test.describe("Phân tích — signed out (Bản minh họa)", () => {
  test("no /v1 request; a cell re-ranks; a row expands in place", async ({ page }) => {
    const api = trackApi(page);
    await enterReplayDemo(page);
    await page.getByRole("region", { name: HOME_MATRIX_REGION }).getByRole("link", { name: /^CTOR Thẻ sản phẩm:/ }).click();
    await expect(page).toHaveURL(/\/analytics\?tab=san-pham&stream=the-san-pham&metric=ctor$/);
    await expectFourDestinationShell(page);

    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^Thẻ sản phẩm: CTOR giảm \d+ %$/);
    await expect(page.getByTestId("mock-data-notice")).toContainText("Cửa hàng Mẫu Hoa Mai");
    await expect(page.getByTestId("juli-suggestion")).toContainText("CTOR kéo GMV −250k ₫/ngày");
    await expect(page.getByRole("heading", { name: "5 sản phẩm kéo CTOR xuống" })).toBeVisible();
    await expect(page.getByTestId("ranking-total")).toContainText("−250k ₫/ngày");

    await page.getByRole("button", { name: /^AOV · Thẻ sản phẩm/ }).click();
    await expect(page).toHaveURL(/stream=the-san-pham&metric=aov$/);
    await expect(page.getByRole("heading", { name: "2 sản phẩm kéo AOV xuống" })).toBeVisible();
    await expect(page.getByTestId("ranking-total")).toContainText("−105k ₫/ngày");

    await page.getByRole("button", { name: /^CTOR · Thẻ sản phẩm/ }).click();
    const sm = row(page, "Son môi số 12");
    await sm.getByRole("button", { expanded: false }).click();
    await expect(sm.getByText("Hai bước của CTOR")).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`row=${SM012}$`));

    await page.getByRole("tab", { name: "Nội dung" }).click();
    await expect(page.getByRole("heading", { name: "Video tác động CTR nhiều nhất" })).toBeVisible();
    await expect(page.getByRole("button", { name: /^CTOR · Video của người bán/ })).toBeDisabled();

    expect(api).toEqual([]);
  });

  test("Xem đề xuất › → the card, highlighted; Xem phân tích › → back on that row", async ({ page }) => {
    const api = trackApi(page);
    await enterReplayDemo(page);
    await page.goto("/analytics");
    await row(page, "Son môi số 12").getByRole("link", { name: "Xem đề xuất ›" }).click();
    await expect(page).toHaveURL(/\/decisions\?tab=de-xuat&the=sample-sm-012$/);
    const card = page.locator('[data-decision-id="sample-sm-012"]');
    await expect(card).toHaveAttribute("data-focused", "true");
    await expect(card).toBeInViewport();
    await expect(card).not.toHaveAttribute("data-focused", "true", { timeout: 5000 });

    await card.getByRole("link", { name: "Xem phân tích ›" }).click();
    await expect(page).toHaveURL(new RegExp(`/analytics\\?tab=san-pham&stream=the-san-pham&metric=ctor&row=${SM012}$`));
    await expect(row(page, "Son môi số 12").getByRole("button", { expanded: true })).toBeVisible();
    await expect(row(page, "Sữa rửa mặt amino")).toContainText("Chưa có đề xuất");
    expect(api).toEqual([]);
  });

  test("streams collapse one at a time; Khuyến mãi and Lịch sale start collapsed", async ({ page }) => {
    await enterReplayDemo(page);
    await page.goto("/analytics");
    const shopTab = page.getByTestId("pa-stream").filter({ has: page.getByRole("heading", { name: "Tab cửa hàng" }) });
    await expect(shopTab.getByText("Yếu nhất: AOV −31k ₫/ngày")).toBeVisible();
    await shopTab.getByRole("button", { name: "Mở" }).click();
    await expect(page.getByRole("button", { name: "Thu gọn" })).toHaveCount(1);
    const promo = page.getByTestId("more-khuyen-mai");
    await expect(promo.getByRole("button", { name: "Xem thêm" })).toHaveAttribute("aria-expanded", "false");
    await promo.getByRole("button", { name: "Xem thêm" }).click();
    await expect(promo.getByText("Giảm thật trung bình")).toBeVisible();
  });

  test("no horizontal page scroll at 390 px; rows stack as cards", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await enterReplayDemo(page);
    await page.goto("/analytics");
    await expect(page.getByTestId("ranking-table")).toBeVisible();
    await expect(page.locator(".pa-mrow").first()).toBeVisible();
    const [scroll, inner] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    expect(scroll).toBeLessThanOrEqual(inner);
  });
});

test("Phân tích passes axe (serious/critical) with a row and Khuyến mãi open", async ({ page }) => {
  await enterReplayDemo(page);
  await page.goto(`/analytics?tab=san-pham&stream=the-san-pham&metric=ctor&row=${SM012}`);
  await expect(page.getByTestId("ranking-table")).toBeVisible();
  await page.getByTestId("more-khuyen-mai").getByRole("button", { name: "Xem thêm" }).click();
  const results = await new AxeBuilder({ page }).include(".pa-page").withTags(["wcag2a", "wcag2aa"]).analyze();
  const blocking = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
  expect(blocking.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`)).toEqual([]);
});

test.describe("Phân tích — signed-in seller (stubbed API)", () => {
  test("reads the report once, the open cell's ranking and the decisions; 404 → empty state", async ({ page }) => {
    await page.addInitScript(() => {
      window.sessionStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
      window.sessionStorage.setItem("juli_demo_active_shop", JSON.stringify({ id: "shop-e2e", name: "Shop E2E" }));
    });
    const { sampleEnvelope, sampleRankings } = await import("../../src/lib/phan-tich/sample-data");
    const report = sampleEnvelope();
    report.report.shop_name = "Shop E2E";
    const rankings = sampleRankings();
    const analysisCalls: string[] = [];
    const rankingCalls: string[] = [];
    let decisionCalls = 0;
    await page.route("**/v1/demo/analysis/rankings*", async (route) => {
      const url = new URL(route.request().url());
      const stream = url.searchParams.get("stream") as keyof typeof rankings;
      const metric = url.searchParams.get("metric") ?? "";
      rankingCalls.push(`${stream}:${metric}`);
      expect(route.request().headers()["authorization"]).toBe("Bearer e2e-token");
      expect(route.request().headers()["x-shop-id"]).toBe("shop-e2e");
      const body = (rankings[stream] as Record<string, unknown> | undefined)?.[metric];
      if (!body || metric === "aov") {
        await route.fulfill({ status: 404, contentType: "application/json", body: '{"detail":"No ranking yet"}' });
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.route(/\/v1\/demo\/analysis(\?.*)?$/, async (route) => {
      analysisCalls.push(route.request().url());
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(report) });
    });
    await page.route(/\/v1\/demo\/decisions(\?.*)?$/, async (route) => {
      decisionCalls += 1;
      await route.fulfill({ status: 200, contentType: "application/json", body: '{"data":[]}' });
    });
    await page.route("**/v1/demo/analytics*", (route) => route.fulfill({ status: 404, body: "{}" }));

    await page.goto("/analytics?tab=san-pham&stream=the-san-pham&metric=ctor");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^Thẻ sản phẩm: CTOR giảm/);
    await expect(page.getByTestId("mock-data-notice")).toHaveCount(0);
    await expect(page.getByTestId("ranking-table")).toBeVisible();
    await expect(row(page, "Son môi số 12")).toContainText("Chưa có đề xuất");
    expect(rankingCalls).toEqual(["product_card:ctor"]);
    expect(decisionCalls).toBe(1);

    await page.getByRole("button", { name: /^AOV · Thẻ sản phẩm/ }).click();
    await expect(page.getByText("Chưa có bảng xếp hạng cho chỉ số này")).toBeVisible();
    expect(rankingCalls).toEqual(["product_card:ctor", "product_card:aov"]);
    expect(analysisCalls).toHaveLength(1);
  });
});
