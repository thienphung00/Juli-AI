import { expect, test } from "@playwright/test";

import { RECOMMENDATION_WORKFLOWS } from "../fixtures/workflow-keys";
import { expectFourDestinationShell } from "../helpers/demo-navigation";

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
      const cardTitles = await page
        .locator("article[data-workflow-key] h3")
        .allTextContents();
      return { navLabels, cardTitles };
    };

    const desktop = await collectLabels();
    await expectFourDestinationShell(page);
    expect(desktop.cardTitles).toEqual(
      RECOMMENDATION_WORKFLOWS.map((fixture) => fixture.title),
    );

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    await page.goto("/decisions");

    const mobile = await collectLabels();
    expect(mobile.navLabels).toEqual(desktop.navLabels);
    expect(mobile.cardTitles).toEqual(desktop.cardTitles);
    await expect(
      page.getByRole("button", { name: "Đề xuất", pressed: true }),
    ).toBeVisible();
  });

  test("Home launcher labels match on desktop and mobile-web", async ({
    page,
  }) => {
    await page.goto("/");
    const desktopLaunchers = await page
      .getByRole("region", { name: "Điểm đến chính" })
      .getByRole("link")
      .allTextContents();

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    const mobileLaunchers = await page
      .getByRole("region", { name: "Điểm đến chính" })
      .getByRole("link")
      .allTextContents();

    expect(mobileLaunchers).toEqual(desktopLaunchers);
  });
});
