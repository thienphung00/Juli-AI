import { expect, test } from "@playwright/test";

import {
  PRIORITY_WORKFLOW,
  RECOMMENDATION_WORKFLOWS,
} from "../fixtures/workflow-keys";
import {
  HOME_MATRIX_REGION,
  enterReplayDemo,
  expectFourDestinationShell,
  expectShopHeader,
  navigatePrimaryDestination,
} from "../helpers/demo-navigation";
import {
  advanceReviewToApproveStage,
  approveFromRecommendations,
  confirmApproveThroughGate,
  satisfyRequiredUploads,
} from "../helpers/workflow-journey";

test.describe("Phase 2.6 exit gate — Decisions journey", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
    // `/` is the two-door landing gate since #1319; Home lives behind the
    // replay door. Enter it so these specs start where they used to.
    await enterReplayDemo(page);
  });

  // AC-8.5 (ADR-109 d.3): Home is the report overview — GMV / Đơn / AOV and
  // the 5-stream matrix — not two launcher cards any more.
  test("Home shows the 5-stream matrix and its cells open Phân tích", async ({ page }) => {
    const matrix = page.getByRole("region", { name: HOME_MATRIX_REGION });
    await expect(matrix).toBeVisible();
    await expect(page.getByTestId("mock-data-notice")).toContainText("Dữ liệu mẫu");
    await expect(page.getByTestId("home-stat-gmv")).toContainText("GMV 30 ngày");
    await expect(matrix.locator("tr[data-channel] > th")).toHaveText([
      /^Thẻ sản phẩm/,
      /^Tab cửa hàng/,
      /^Video của shop/,
      /^LIVE của shop/,
      /^Liên kết/,
    ]);
    await matrix.getByRole("link", { name: /^CTOR Thẻ sản phẩm:/ }).click();
    await expect(page).toHaveURL(/\/analytics\?tab=san-pham&stream=the-san-pham&metric=ctor$/);
  });

  test("Home → Decisions via the rail preserves the four-destination shell", async ({
    page,
  }) => {
    await navigatePrimaryDestination(page, "Quyết định");
    await expect(page).toHaveURL(/\/decisions$/);
    await expectFourDestinationShell(page);
    await expectShopHeader(page);
    await expect(page.getByRole("tab", { name: "Đề xuất" })).toHaveAttribute("aria-selected", "true");
    // P11: the signed-out Quyết định is the P10 sample ("Bản minh họa").
    await expect(page.getByTestId("mock-data-notice")).toContainText("Dữ liệu mẫu");
  });

  test("the P10 sample cards render in a stable order (SM-012 first)", async ({ page }) => {
    await page.goto("/decisions");
    const cards = page.getByTestId("recommendation-card");
    await expect(cards.first()).toContainText("SKU · SM-012");
    const first = await cards.locator("h3").allTextContents();
    await page.reload();
    await expect(cards.first()).toContainText("SKU · SM-012");
    expect(await cards.locator("h3").allTextContents()).toEqual(first);
  });

  test("Priority Workflow 1 completes review → approve → In Progress", async ({
    page,
  }) => {
    await approveFromRecommendations(
      page,
      PRIORITY_WORKFLOW.workflowKey,
      PRIORITY_WORKFLOW.subject,
    );
    await expect(
      page.getByRole("heading", { name: PRIORITY_WORKFLOW.title, level: 1 }),
    ).toBeVisible();
    await expect(page.getByText("Đang thực hiện")).toBeVisible();
  });

  test("every executable workflow reaches In Progress in one session", async ({
    page,
  }) => {
    // P11: signed-out /decisions is the P10 sample and no longer links to the
    // fixture review routes; each route is opened directly instead.
    for (const fixture of RECOMMENDATION_WORKFLOWS) {
      await page.goto(`/decisions/recommendations/${fixture.workflowKey}`);
      await advanceReviewToApproveStage(page);
      await satisfyRequiredUploads(page);
      await confirmApproveThroughGate(page);
      await expect(page).toHaveURL(/\/decisions\/in-progress\//);
      if (fixture.workflowKey === "optimize_product_2") {
        // #1320 part 2 deleted Optimize Product's mock execution: approving now
        // reaches the staged run view (the captured replay run) instead of a
        // titled mock-execution detail page, so there is no `h1` carrying the
        // workflow title to assert. The stepper is what this workflow renders.
        await expect(
          page.getByRole("tablist", { name: "Các bước xử lý" }),
        ).toBeVisible();
      } else {
        await expect(
          page.getByRole("heading", { name: fixture.title, level: 1 }),
        ).toBeVisible();
      }
    }
  });
});
