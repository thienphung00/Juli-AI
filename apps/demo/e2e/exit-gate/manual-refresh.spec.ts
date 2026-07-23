import { expect, test } from "@playwright/test";

import { RECOMMENDATION_WORKFLOWS } from "../fixtures/workflow-keys";
import { resetDemo } from "../helpers/workflow-journey";

test.describe("Phase 2.6 exit gate — Manual Refresh", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/decisions");
    await page.evaluate(() => localStorage.clear());
    await page.reload();
  });

  test("resets mutated Decisions state and returns to Recommendations", async ({
    page,
  }) => {
    const firstCard = page.locator(
      `article[data-workflow-key="${RECOMMENDATION_WORKFLOWS[0].workflowKey}"]`,
    );
    await firstCard.getByRole("button", { name: "Từ chối" }).click();
    await expect(firstCard).toHaveCount(0);

    await resetDemo(page);

    await expect(
      page.getByRole("button", { name: "Đề xuất", pressed: true }),
    ).toBeVisible();
    await expect(
      page.locator("article[data-workflow-key]"),
    ).toHaveCount(RECOMMENDATION_WORKFLOWS.length);
  });

  test("from mutated Home state, refresh returns to Decisions Recommendations", async ({
    page,
  }) => {
    await page.goto("/decisions");
    await page
      .locator(
        `article[data-workflow-key="${RECOMMENDATION_WORKFLOWS[1].workflowKey}"]`,
      )
      .getByRole("button", { name: "Từ chối" })
      .click();
    await page.goto("/");
    await resetDemo(page);
    await expect(page).toHaveURL(/\/decisions$/);
    await expect(
      page.locator("article[data-workflow-key]"),
    ).toHaveCount(RECOMMENDATION_WORKFLOWS.length);
  });
});
