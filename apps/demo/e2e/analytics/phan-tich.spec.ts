import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { HOME_MATRIX_REGION, enterReplayDemo, expectFourDestinationShell } from "../helpers/demo-navigation";

/**
 * Phân tích (AC-8.6, ADR-109 decisions 2–5) end to end: the anonymous door
 * (bundled sample, no request) and a stubbed signed-in seller (the report
 * read once, rankings read per clicked cell, 404 → honest empty state).
 */

const LIB = resolve(dirname(fileURLToPath(import.meta.url)), "../../src/lib/shop-analysis");
const REPORT = JSON.parse(readFileSync(resolve(LIB, "sample-report.json"), "utf8"));
const RANKINGS = JSON.parse(readFileSync(resolve(LIB, "sample-rankings.json"), "utf8"));

function trackApi(page: Page): string[] {
  const urls: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/v1/")) urls.push(`${url.pathname}${url.search}`);
  });
  return urls;
}

test.describe("Phân tích — anonymous sample", () => {
  test("a Home cell lands on its stream × metric; cells re-rank; rows open the Ví dụ panel", async ({ page }) => {
    const api = trackApi(page);
    await enterReplayDemo(page);
    await page
      .getByRole("region", { name: HOME_MATRIX_REGION })
      .getByRole("link", { name: /^CTOR Thẻ sản phẩm:/ })
      .click();
    await expect(page).toHaveURL(/\/analytics\?tab=san-pham&stream=the-san-pham&metric=ctor$/);
    await expectFourDestinationShell(page);

    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Thẻ sản phẩm: CTOR giảm 15,2 %");
    await expect(page.getByTestId("mock-data-notice")).toBeVisible();
    await expect(page.getByRole("button", { name: /^CTOR · Thẻ sản phẩm/ })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("juli-suggestion")).toContainText("Tối ưu CTOR");
    await expect(page.getByRole("heading", { name: "SKU kéo CTOR xuống" })).toBeVisible();
    await expect(page.getByTestId("ranking-total")).toContainText("Tổng = −587.989 ₫");

    await page.getByRole("button", { name: /Thớt gỗ tròn 30cm/ }).click();
    await expect(page.getByTestId("detail-panel")).toContainText("Ví dụ · s7");

    await page.getByRole("button", { name: /^AOV · Thẻ sản phẩm/ }).click();
    await expect(page).toHaveURL(/stream=the-san-pham&metric=aov$/);
    await expect(page.getByRole("heading", { name: "SKU kéo AOV xuống" })).toBeVisible();

    await page.getByRole("tab", { name: "Nội dung" }).click();
    await expect(page).toHaveURL(/\/analytics\?tab=noi-dung$/);
    const video = page.getByRole("article", { name: "Video của shop" });
    await expect(video.getByText("phụ thuộc sản phẩm → xem tab Sản phẩm")).toHaveCount(2);
    await page.getByRole("button", { name: /^CTOR · gồm mua ngay · LIVE của shop/ }).click();
    await expect(page.getByRole("heading", { name: "Phiên LIVE kéo CTOR xuống" })).toBeVisible();

    expect(api).toEqual([]);
  });

  test("Khuyến mãi and Dòng thời gian are collapsed until Xem thêm; heroes expand in place", async ({ page }) => {
    await enterReplayDemo(page);
    await page.goto("/analytics");
    const promos = page.getByTestId("more-khuyen-mai");
    await expect(promos.getByRole("button", { name: "Xem thêm" })).toHaveAttribute("aria-expanded", "false");
    await promos.getByRole("button", { name: "Xem thêm" }).click();
    await expect(promos.getByRole("button", { name: "Thu gọn" })).toBeVisible();

    const timeline = page.getByTestId("more-dong-thoi-gian");
    await timeline.getByRole("button", { name: "Xem thêm" }).click();
    await expect(timeline.locator("svg").first()).toBeVisible();

    const hero = page.getByRole("button", { name: /Hộp cơm giữ nhiệt 3 tầng/ });
    await hero.click();
    await expect(hero).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("region", { name: "Chỉ số của Hộp cơm giữ nhiệt 3 tầng" })).toBeVisible();
  });

  test("no horizontal page scroll", async ({ page }) => {
    await enterReplayDemo(page);
    await page.goto("/analytics");
    await expect(page.getByTestId("ranking-table")).toBeVisible();
    await page.getByTestId("more-khuyen-mai").getByRole("button", { name: "Xem thêm" }).click();
    const [scroll, inner, widest] = await page.evaluate(() => [
      document.documentElement.scrollWidth,
      window.innerWidth,
      Math.max(...[...document.querySelectorAll(".pt-page .card > *, .pt-page [class*=\"table-wrap\"]")].map((el) => el.getBoundingClientRect().right)),
    ]);
    expect(scroll).toBeLessThanOrEqual(inner);
    // Wide tables scroll inside their own region; nothing spills out of a card.
    expect(widest).toBeLessThanOrEqual(inner);
  });
});

test("Phân tích passes axe (serious/critical) with a section and a hero open", async ({ page }) => {
  await enterReplayDemo(page);
  await page.goto("/analytics");
  await expect(page.getByTestId("ranking-table")).toBeVisible();
  await page.getByTestId("more-khuyen-mai").getByRole("button", { name: "Xem thêm" }).click();
  await page.getByRole("button", { name: /Hộp cơm giữ nhiệt 3 tầng/ }).click();
  const results = await new AxeBuilder({ page }).include(".pt-page").withTags(["wcag2a", "wcag2aa"]).analyze();
  const blocking = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
  expect(blocking.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`)).toEqual([]);
});

test.describe("Phân tích — signed-in seller (stubbed API)", () => {
  test("reads the report once and each clicked cell's ranking; 404 → empty state", async ({ page }) => {
    await page.addInitScript(() => {
      window.sessionStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
      window.sessionStorage.setItem("juli_demo_active_shop", JSON.stringify({ id: "shop-e2e", name: "Shop E2E" }));
    });
    const report = structuredClone(REPORT);
    report.report.shop_name = "Shop E2E";
    const analysisCalls: string[] = [];
    const rankingCalls: string[] = [];
    await page.route("**/v1/demo/analysis/rankings*", async (route) => {
      const url = new URL(route.request().url());
      rankingCalls.push(`${url.searchParams.get("stream")}:${url.searchParams.get("metric")}`);
      expect(route.request().headers()["authorization"]).toBe("Bearer e2e-token");
      expect(route.request().headers()["x-shop-id"]).toBe("shop-e2e");
      const body = RANKINGS[url.searchParams.get("stream") ?? ""]?.[url.searchParams.get("metric") ?? ""];
      if (!body || url.searchParams.get("metric") === "aov") {
        await route.fulfill({ status: 404, contentType: "application/json", body: '{"detail":"No ranking yet"}' });
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.route(/\/v1\/demo\/analysis(\?.*)?$/, async (route) => {
      analysisCalls.push(route.request().url());
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(report) });
    });
    // Other shell reads (KPI analytics, shops) are not under test here.
    await page.route("**/v1/demo/analytics*", (route) => route.fulfill({ status: 404, body: "{}" }));

    await page.goto("/analytics?tab=san-pham&stream=the-san-pham&metric=ctor");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Thẻ sản phẩm: CTOR giảm 15,2 %");
    await expect(page.getByTestId("mock-data-notice")).toHaveCount(0);
    await expect(page.getByTestId("ranking-table")).toBeVisible();
    expect(rankingCalls).toEqual(["product_card:ctor"]);

    await page.getByRole("button", { name: /^AOV · Thẻ sản phẩm/ }).click();
    await expect(page.getByText("Chưa có bảng xếp hạng cho chỉ số này")).toBeVisible();
    expect(rankingCalls).toEqual(["product_card:ctor", "product_card:aov"]);
    expect(analysisCalls).toHaveLength(1);
  });
});
