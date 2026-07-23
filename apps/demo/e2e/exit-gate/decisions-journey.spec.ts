import { expect, test } from "@playwright/test";

import {
  PRIORITY_WORKFLOW,
  RECOMMENDATION_WORKFLOWS,
} from "../fixtures/workflow-keys";
import {
  expectContextualAssistance,
  expectFourDestinationShell,
} from "../helpers/demo-navigation";
import {
  advanceReviewToApproveStage,
  approveFromRecommendations,
} from "../helpers/workflow-journey";

test.describe("Phase 2.6 exit gate — Decisions journey", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => localStorage.clear());
    await page.reload();
  });

  test("Home exposes exactly two destination launchers", async ({ page }) => {
    await expect(
      page.getByRole("region", { name: "Điểm đến chính" }),
    ).toBeVisible();
    const launchers = page
      .getByRole("region", { name: "Điểm đến chính" })
      .getByRole("link");
    await expect(launchers).toHaveCount(2);
    const launcherRegion = page.getByRole("region", { name: "Điểm đến chính" });
    await expect(
      launcherRegion.getByRole("link", { name: /Quyết định/ }),
    ).toHaveAttribute("href", "/decisions");
    await expect(
      launcherRegion.getByRole("link", { name: /Phân tích/ }),
    ).toHaveAttribute("href", "/analytics");
    await expect(page.getByTestId("mock-data-notice")).toContainText(
      "Juli Demo Shop",
    );
  });

  test("Home → Decisions preserves four-destination shell and assistance", async ({
    page,
  }) => {
    await page
      .getByRole("region", { name: "Điểm đến chính" })
      .getByRole("link", { name: /Quyết định/ })
      .click();
    await expect(page).toHaveURL(/\/decisions$/);
    await expectFourDestinationShell(page);
    await expectContextualAssistance(page);
    await expect(
      page.getByRole("button", { name: "Đề xuất", pressed: true }),
    ).toBeVisible();
  });

  test("Priority Workflow 1 is first and marked ★ Ưu tiên", async ({ page }) => {
    await page.goto("/decisions");
    const cards = page.locator("article[data-workflow-key]");
    await expect(cards).toHaveCount(RECOMMENDATION_WORKFLOWS.length);

    const firstKey = await cards.first().getAttribute("data-workflow-key");
    expect(firstKey).toBe(PRIORITY_WORKFLOW.workflowKey);
    await expect(cards.first().getByText("★ Ưu tiên")).toBeVisible();
  });

  test("all recommendation cards render in stable specification order", async ({
    page,
  }) => {
    await page.goto("/decisions");
    const keys = await page
      .locator("article[data-workflow-key]")
      .evaluateAll((nodes) =>
        nodes.map((node) => node.getAttribute("data-workflow-key")),
      );

    expect(keys).toEqual(
      RECOMMENDATION_WORKFLOWS.map((fixture) => fixture.workflowKey),
    );
  });

  test("Priority Workflow 1 completes review → approve → In Progress", async ({
    page,
  }) => {
    await approveFromRecommendations(
      page,
      PRIORITY_WORKFLOW.workflowKey,
      PRIORITY_WORKFLOW.title,
    );
    await expect(
      page.getByRole("heading", { name: PRIORITY_WORKFLOW.title, level: 1 }),
    ).toBeVisible();
    await expect(page.getByText("Đang thực hiện")).toBeVisible();
  });

  test("every executable workflow reaches In Progress in one session", async ({
    page,
  }) => {
    await page.goto("/decisions");

    for (const fixture of RECOMMENDATION_WORKFLOWS) {
      const card = page.locator(
        `article[data-workflow-key="${fixture.workflowKey}"]`,
      );
      await expect(card).toBeVisible();
      await card.getByRole("button", { name: "Phê duyệt" }).click();
      await expect(page).toHaveURL(
        new RegExp(`/decisions/recommendations/${fixture.workflowKey}$`),
      );
      await advanceReviewToApproveStage(page);
      await page.getByRole("button", { name: "Phê duyệt" }).last().click();
      await expect(page).toHaveURL(/\/decisions\/in-progress\//);
      await expect(
        page.getByRole("heading", { name: fixture.title, level: 1 }),
      ).toBeVisible();
      await page.goto("/decisions");
      await expect(
        page.getByRole("button", { name: "Đề xuất", pressed: true }),
      ).toBeVisible();
      await expect(card).toHaveCount(0);
    }
  });
});
