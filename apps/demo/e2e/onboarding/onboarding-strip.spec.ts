import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

import { decision, MAIN_CARD } from "../decisions/p10-fixtures";

/**
 * P17 (D26, `fasttrack/contracts/p17-onboarding-speed.md` §1–2): a signed-in
 * seller whose shop Juli is still reading sees "Juli đang đọc dữ liệu shop ·
 * bước N/3" on Trang chủ, Phân tích and Quyết định; on Quyết định a quick-scan
 * card appears after the next poll (15 s), with its "Đề xuất nhanh · dựa trên
 * 14 ngày" chip. The anonymous door makes no onboarding request.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const REPORT = JSON.parse(readFileSync(resolve(HERE, "../../src/lib/shop-analysis/sample-report.json"), "utf8"));

const ACTIVE = {
  shop_id: "shop-e2e",
  active: true,
  current_step: 2,
  total_steps: 3,
  label: "Juli đang đọc dữ liệu shop · bước 2/3",
  poll_interval_seconds: 15,
  steps: [
    { key: "quick_scan", label: "Quét nhanh 14 ngày", status: "done", percent: 100, eta_seconds: null, detail: "1 đề xuất nhanh" },
    { key: "backfill_diagnosis", label: "Đọc 60 ngày và chẩn đoán đầy đủ", status: "running", percent: 40, eta_seconds: 540, detail: "24/60 ngày" },
    { key: "history", label: "Tải lịch sử nền", status: "pending", percent: 13, eta_seconds: null, detail: null },
  ],
  history_days_available: 24,
  history_target_days: 180,
  history_days_remaining: 156,
  history_complete: false,
  window_90d_available: false,
};

const QUICK = (() => {
  const item = decision({ ...MAIN_CARD, id: "q1", lever: "title", kpi: "ctr", current: 0.021, target: 0.028 });
  return {
    ...item,
    recommendation: {
      ...item.recommendation,
      card: {
        ...item.recommendation.card,
        quick_scan: {
          label: "Đề xuất nhanh · dựa trên 14 ngày",
          confidence: "Tham khảo",
          window_days: 14,
          basis: "GMV dự kiến theo công thức D22 trên 14 ngày gần nhất (trung bình/ngày), mã chẩn đoán TikTok",
        },
      },
    },
  };
})();

async function signedIn(page: Page) {
  await page.addInitScript(() => {
    window.sessionStorage.setItem("juli_demo_auth_session", JSON.stringify({ accessToken: "e2e-token", tokenType: "bearer" }));
    window.sessionStorage.setItem("juli_demo_active_shop", JSON.stringify({ id: "shop-e2e", name: "Shop E2E" }));
  });
  const report = structuredClone(REPORT);
  report.report.shop_name = "Shop E2E";
  const state = { onboardingReads: 0 };
  // Registered first = matched last: anything not stubbed below is a 404.
  await page.route("**/v1/**", (route) => route.fulfill({ status: 404, contentType: "application/json", body: "{}" }));
  await page.route(/\/v1\/demo\/analysis(\?.*)?$/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(report) }),
  );
  await page.route("**/v1/shops/me/onboarding", (route) => {
    state.onboardingReads += 1;
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ACTIVE) });
  });
  // No card until the quick scan has written one (after the first onboarding poll).
  await page.route("**/v1/demo/decisions", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ success: true, data: state.onboardingReads >= 2 ? [QUICK] : [], error: null }),
    }),
  );
  await page.route(/\/v1\/demo\/runs$/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ success: true, data: [] }) }),
  );
  return state;
}

test("Trang chủ, Phân tích and Quyết định show the onboarding strip", async ({ page }) => {
  await signedIn(page);
  for (const path of ["/", "/analytics", "/decisions"]) {
    await page.goto(path);
    const strip = page.getByTestId("onboarding-strip");
    await expect(strip).toContainText("Juli đang đọc dữ liệu shop · bước 2/3");
    await expect(strip.getByTestId("onboarding-step")).toHaveCount(3);
    await expect(strip).toContainText("Đang chạy · 40 % · khoảng 9 phút");
  }
});

test("Quyết định: a quick-scan card appears after the next onboarding poll", async ({ page }) => {
  const state = await signedIn(page);
  await page.goto("/decisions");
  await expect(page.getByTestId("onboarding-strip")).toBeVisible();
  await expect(page.getByTestId("recommendation-card")).toHaveCount(0);
  await expect.poll(() => state.onboardingReads, { timeout: 30_000 }).toBeGreaterThanOrEqual(2);
  const card = page.getByTestId("recommendation-card").first();
  await expect(card).toBeVisible({ timeout: 20_000 });
  await expect(card.getByTestId("quick-scan-chip")).toHaveText("Đề xuất nhanh · dựa trên 14 ngày");
  await expect(card.getByTestId("quick-scan-confidence")).toHaveText("Độ tin cậy: Tham khảo");
});

test("anonymous visitors get no strip and no onboarding request", async ({ page }) => {
  const calls: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/v1/shops/me/onboarding") calls.push(request.url());
  });
  await page.goto("/decisions");
  await expect(page.getByTestId("recommendation-card").first()).toBeVisible();
  await expect(page.getByTestId("onboarding-strip")).toHaveCount(0);
  expect(calls).toEqual([]);
});
