import { expect, test } from "@playwright/test";

import {
  HOME_MATRIX_REGION,
  enterReplayDemo,
  expectFourDestinationShell,
} from "../helpers/demo-navigation";

test.describe("Phase 2.6 exit gate — responsive IA parity", () => {
  test("Decisions journey preserves terminology and card order across breakpoints", async ({
    page,
  }) => {
    await page.goto("/decisions");

    const collectLabels = async () => {
      const navLabels = await page
        .getByRole("navigation", { name: "Điều hướng chính" })
        .getByRole("link")
        .allTextContents();
      await expect(page.getByTestId("recommendation-card").first()).toBeVisible();
      const cardTitles = await page
        .getByTestId("recommendation-card")
        .locator("h3")
        .allTextContents();
      return { navLabels, cardTitles };
    };

    const desktop = await collectLabels();
    await expectFourDestinationShell(page);
    // P11: the signed-out Quyết định is the P10 sample; the card h3 is the product.
    expect(desktop.cardTitles[0]).toBe("Son môi số 12");
    expect(desktop.cardTitles.length).toBeGreaterThanOrEqual(4);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    await page.goto("/decisions");

    const mobile = await collectLabels();
    expect(mobile.navLabels).toEqual(desktop.navLabels);
    expect(mobile.cardTitles).toEqual(desktop.cardTitles);
    await expect(page.getByRole("tab", { name: "Đề xuất" })).toHaveAttribute("aria-selected", "true");
  });

  test("Home matrix labels match on desktop and mobile-web", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await enterReplayDemo(page);
    const read = () =>
      page.getByRole("region", { name: HOME_MATRIX_REGION }).locator("tr[data-channel] > th").allTextContents();
    const desktop = await read();

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    await expect(page.getByRole("region", { name: HOME_MATRIX_REGION })).toBeVisible();
    expect(await read()).toEqual(desktop);
  });

  // ADR-109 decision 7: a left rail from 768px, a bottom bar below it — the
  // same <nav>, moved by CSS, with the same four items.
  test("navigation is a left rail at 1440px and a bottom bar at 390px", async ({ page }) => {
    const nav = page.getByRole("navigation", { name: "Điều hướng chính" });

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/decisions");
    await expectFourDestinationShell(page);
    const rail = await nav.boundingBox();
    expect(rail).not.toBeNull();
    expect(rail!.x).toBeLessThan(120);
    expect(rail!.height).toBeGreaterThan(rail!.width);
    await expect(page.getByRole("link", { name: "Juli — Trang chủ" })).toBeVisible();

    await page.setViewportSize({ width: 390, height: 844 });
    await expectFourDestinationShell(page);
    const bar = await nav.boundingBox();
    expect(bar).not.toBeNull();
    expect(bar!.width).toBeGreaterThan(bar!.height);
    expect(Math.round(bar!.y + bar!.height)).toBe(844);
    await expect(page.getByRole("link", { name: "Juli — Trang chủ" })).toBeHidden();
  });
});
