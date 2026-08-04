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
    await Promise.all([
      page.waitForURL(
        new RegExp(
          `/decisions/recommendations/${PRIORITY_WORKFLOW.workflowKey}$`,
        ),
      ),
      priorityCard.getByRole("button", { name: "Phê duyệt" }).click(),
    ]);
    await advanceReviewToApproveStage(page);
  });

  test("Analytics chart equivalent exposes sr-only label when unavailable", async ({
    page,
  }) => {
    // A live envelope can still omit series data for one of the five Demo
    // Main KPIs (ADR-049) even though the catalog itself marks all five
    // selectable — DUX-1's fallback only covers total fetch failure, not a
    // per-KPI data gap in an otherwise-valid 200 response.
    await page.route("**/v1/demo/analytics*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          envelope_version: 1,
          kind: "analytics",
          shop_id: "00000000-0000-4000-8000-000000000001",
          computed_at: new Date().toISOString(),
          currency: "VND",
          kpis: {
            gmv_tiktok: {
              availability: "available",
              label: "GMV (TikTok)",
              series: [
                { t: "2026-07-13", v: 400_000_000 },
                { t: "2026-07-20", v: 420_000_000 },
              ],
            },
            aov: { availability: "unavailable", label: "AOV", series: [] },
            ctor: {
              availability: "available",
              label: "CTOR",
              series: [
                { t: "2026-07-13", v: 3.2 },
                { t: "2026-07-20", v: 3.5 },
              ],
            },
            live_hours: {
              availability: "available",
              label: "LIVE hours",
              series: [
                { t: "2026-07-13", v: 8 },
                { t: "2026-07-20", v: 12 },
              ],
            },
            cancellation_rate: {
              availability: "available",
              label: "Cancellation rate",
              series: [
                { t: "2026-07-13", v: 2.1 },
                { t: "2026-07-20", v: 1.8 },
              ],
            },
          },
          meta: { source_partitions: ["live"] },
        }),
      });
    });

    await page.goto("/analytics");
    const unavailableCard = page.getByTestId("analytics-kpi-card-aov");
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
