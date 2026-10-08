import { expect, test, type Page } from "@playwright/test";

import {
  expectFourDestinationShell,
  navigatePrimaryDestination,
} from "../helpers/demo-navigation";

/** Branded CSS must override UA defaults — static bundles failed to load otherwise. */
async function expectBrandedComputedStyles(page: Page) {
  const styles = await page.evaluate(() => {
    const body = getComputedStyle(document.body);
    const wordmark = document.querySelector(".demo-wordmark");
    const wordmarkStyles = wordmark ? getComputedStyle(wordmark) : null;
    return {
      bodyFontFamily: body.fontFamily,
      bodyBackgroundColor: body.backgroundColor,
      wordmarkBackgroundImage: wordmarkStyles?.backgroundImage ?? "",
      wordmarkFontWeight: wordmarkStyles?.fontWeight ?? "",
      wordmarkFontSize: wordmarkStyles?.fontSize ?? "",
    };
  });

  expect(styles.bodyFontFamily.toLowerCase()).toMatch(/inter/);
  // D21 restyle: flat app-kit background instead of the brand gradient image.
  expect(styles.bodyBackgroundColor).not.toBe("rgba(0, 0, 0, 0)");
  expect(styles.wordmarkFontWeight).toBe("800");
  expect(parseFloat(styles.wordmarkFontSize)).toBeGreaterThan(16);
  // D21 app kit: the wordmark is gradient text (.brand-wordmark), not a flat pink.
  expect(styles.wordmarkBackgroundImage).toMatch(/gradient/);
}

test.describe("Phase 2.6 exit gate — static asset render (ADR-035)", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => localStorage.clear());
    await page.reload();
  });

  test("Home loads branded computed styles from production CSS bundles", async ({
    page,
  }) => {
    await expect(page.getByRole("link", { name: "Juli" })).toBeVisible();
    await expectBrandedComputedStyles(page);
  });

  test("Home → Decisions via primary nav preserves branded shell", async ({
    page,
  }) => {
    await expectBrandedComputedStyles(page);

    await navigatePrimaryDestination(page, "Quyết định");
    await expect(page).toHaveURL(/\/decisions$/);
    await expectFourDestinationShell(page);
    await expect(
      page.getByRole("button", { name: "Đề xuất", pressed: true }),
    ).toBeVisible();
    await expectBrandedComputedStyles(page);
  });

  test("Decisions direct load keeps non-default styling", async ({ page }) => {
    await page.goto("/decisions");
    await expectBrandedComputedStyles(page);
    await expectFourDestinationShell(page);
  });
});
