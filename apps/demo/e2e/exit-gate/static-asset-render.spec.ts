import { expect, test, type Page } from "@playwright/test";

import {
  expectFourDestinationShell,
  navigatePrimaryDestination,
} from "../helpers/demo-navigation";

/**
 * Branded CSS must override UA defaults — static bundles failed to load
 * otherwise. AC-8.5: the brand now shows in the shell the sales demo video
 * draws — the active rail/bottom-bar item's pink tint and pink text, and the
 * avatar's brand gradient — at both viewports (the Juli. wordmark sits in the
 * desktop rail only).
 */
async function expectBrandedComputedStyles(page: Page) {
  await expect(page.locator(".app-nav__item[aria-current='page']")).toBeVisible();
  await expect(page.locator(".shop-avatar")).toBeVisible();
  const styles = await page.evaluate(() => {
    const body = getComputedStyle(document.body);
    const active = document.querySelector(".app-nav__item[aria-current='page']");
    const activeStyles = active ? getComputedStyle(active) : null;
    const avatar = document.querySelector(".shop-avatar");
    const avatarStyles = avatar ? getComputedStyle(avatar) : null;
    return {
      bodyFontFamily: body.fontFamily,
      bodyBackgroundColor: body.backgroundColor,
      activeColor: activeStyles?.color ?? "",
      activeBackground: activeStyles?.backgroundColor ?? "",
      avatarBackgroundImage: avatarStyles?.backgroundImage ?? "",
      avatarFontWeight: avatarStyles?.fontWeight ?? "",
    };
  });

  expect(styles.bodyFontFamily.toLowerCase()).toMatch(/inter/);
  expect(styles.bodyBackgroundColor).not.toBe("rgba(0, 0, 0, 0)");
  // --pink-text (#b0386a) on --pink-background (#fef5f6).
  expect(styles.activeColor).toBe("rgb(176, 56, 106)");
  expect(styles.activeBackground).toBe("rgb(254, 245, 246)");
  expect(styles.avatarBackgroundImage).toMatch(/gradient/);
  expect(styles.avatarFontWeight).toBe("800");
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
    await expect(page.getByRole("navigation", { name: "Điều hướng chính" })).toBeVisible();
    await expectBrandedComputedStyles(page);
  });

  test("Home → Decisions via primary nav preserves branded shell", async ({
    page,
  }) => {
    await expectBrandedComputedStyles(page);

    await navigatePrimaryDestination(page, "Quyết định");
    await expect(page).toHaveURL(/\/decisions$/);
    await expectFourDestinationShell(page);
    await expect(page.getByRole("tab", { name: "Đề xuất" })).toHaveAttribute("aria-selected", "true");
    await expectBrandedComputedStyles(page);
  });

  test("Decisions direct load keeps non-default styling", async ({ page }) => {
    await page.goto("/decisions");
    await expectBrandedComputedStyles(page);
    await expectFourDestinationShell(page);
  });
});
