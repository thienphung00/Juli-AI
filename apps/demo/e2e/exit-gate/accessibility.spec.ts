import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";


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
    // P11: the signed-out Quyết định is the P10 sample; its first card is SM-012.
    const approve = page
      .getByTestId("recommendation-card")
      .first()
      .getByRole("button", { name: "Duyệt" });
    await expect(approve).toBeVisible();
    const box = await approve.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
    expect(box!.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET_PX);
  });

  test("keyboard flow: tab reaches Duyệt with focus-visible", async ({
    page,
  }) => {
    await page.keyboard.press("Tab");
    const focused = page.locator(":focus-visible");
    await expect(focused).toBeVisible();

    for (let i = 0; i < 30; i += 1) {
      await page.keyboard.press("Tab");
      const approve = page
        .getByTestId("recommendation-card")
        .first()
        .getByRole("button", { name: "Duyệt" });
      if (await approve.evaluate((node) => node === document.activeElement)) {
        await expect(approve).toBeFocused();
        return;
      }
    }

    throw new Error("Could not keyboard-focus Duyệt on the first card");
  });

  test("respects prefers-reduced-motion: the sample cards render and expand", async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/decisions");
    const card = page.getByTestId("recommendation-card").first();
    await card.getByRole("button", { name: /Xem thêm/ }).click();
    await expect(card).toContainText("Lý do đầy đủ");
  });
});
