import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { PRIORITY_WORKFLOW } from "../fixtures/workflow-keys";
import {
  advanceReviewToApproveStage,
} from "../helpers/workflow-journey";

const MIN_TOUCH_TARGET_PX = 44;

test.describe("Phase 2.6 exit gate — accessibility", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/decisions");
    await page.evaluate(() => localStorage.clear());
    await page.reload();
  });

  test("Decisions Recommendations passes axe (serious/critical)", async ({
    page,
  }) => {
    const results = await new AxeBuilder({ page })
      .disableRules(["color-contrast"])
      .analyze();
    expect(results.violations.filter((v) => v.impact === "critical")).toEqual(
      [],
    );
    expect(results.violations.filter((v) => v.impact === "serious")).toEqual([]);
  });

  test("primary actions meet 44×44px touch targets", async ({ page }) => {
    const approve = page
      .locator(
        `article[data-workflow-key="${PRIORITY_WORKFLOW.workflowKey}"]`,
      )
      .getByRole("button", { name: "Phê duyệt" });
    const box = await approve.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
    expect(box!.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
  });

  test("keyboard flow: tab reaches Phê duyệt with focus-visible", async ({
    page,
  }) => {
    await page.keyboard.press("Tab");
    const focused = page.locator(":focus-visible");
    await expect(focused).toBeVisible();

    for (let i = 0; i < 30; i += 1) {
      await page.keyboard.press("Tab");
      const approve = page
        .locator(
          `article[data-workflow-key="${PRIORITY_WORKFLOW.workflowKey}"]`,
        )
        .getByRole("button", { name: "Phê duyệt" });
      if (await approve.evaluate((node) => node === document.activeElement)) {
        await expect(approve).toBeFocused();
        return;
      }
    }

    throw new Error("Could not keyboard-focus Phê duyệt on Priority card");
  });

  test("review stages advance through Tiếp theo to final Phê duyệt", async ({
    page,
  }) => {
    await page.goto("/decisions");
    const priorityCard = page.locator(
      `article[data-workflow-key="${PRIORITY_WORKFLOW.workflowKey}"]`,
    );
    await priorityCard.scrollIntoViewIfNeeded();
    await priorityCard
      .getByRole("button", { name: "Phê duyệt" })
      .click({ force: true });
    await advanceReviewToApproveStage(page);
  });

  test("Analytics chart equivalent exposes sr-only label when unavailable", async ({
    page,
  }) => {
    await page.goto("/analytics");
    const unavailableCard = page.getByTestId("analytics-kpi-card-sps");
    await expect(
      unavailableCard.getByText("Chưa khả dụng", { exact: true }),
    ).toBeVisible();
    await expect(
      unavailableCard.locator(".juli-sr-only"),
    ).toContainText(/biểu đồ chưa khả dụng/i);
  });

  test("respects prefers-reduced-motion for scroll-into-view highlight", async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/decisions?highlight=optimize_product_2");
    await expect(
      page.locator('article[data-workflow-key="optimize_product_2"]'),
    ).toBeVisible();
  });
});
