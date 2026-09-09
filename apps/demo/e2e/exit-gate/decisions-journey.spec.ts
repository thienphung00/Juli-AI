import { expect, test } from "@playwright/test";

import {
  PRIORITY_WORKFLOW,
  RECOMMENDATION_WORKFLOWS,
} from "../fixtures/workflow-keys";
import {
  enterReplayDemo,
  expectContextualAssistance,
  expectFourDestinationShell,
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
    const cards = page.locator("article[data-workflow-key]");

    // `evaluateAll` snapshots the DOM once, with no auto-retry -- run it before
    // hydration finishes and it returns `[]`, which is how this test flaked on
    // main-tier while its sibling above (which uses an auto-retrying
    // `toHaveCount`) passed in the same run. Wait for the count first, then read.
    await expect(cards).toHaveCount(RECOMMENDATION_WORKFLOWS.length);

    const keys = await cards.evaluateAll((nodes) =>
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
    // beforeEach already entered through the replay door; navigate within the
    // shell rather than re-loading `/decisions` cold, which would land on the
    // landing gate with no entry choice recorded.
    await page
      .getByRole("region", { name: "Điểm đến chính" })
      .getByRole("link", { name: /Quyết định/ })
      .click();
    await expect(page).toHaveURL(/\/decisions$/);

    for (const fixture of RECOMMENDATION_WORKFLOWS) {
      const card = page.locator(
        `article[data-workflow-key="${fixture.workflowKey}"]`,
      );
      await expect(card).toBeVisible();
      await card.scrollIntoViewIfNeeded();
      await Promise.all([
        page.waitForURL(
          new RegExp(`/decisions/recommendations/${fixture.workflowKey}$`),
        ),
        card.getByRole("button", { name: "Phê duyệt" }).click(),
      ]);
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
      await page.goto("/decisions");
      await expect(
        page.getByRole("button", { name: "Đề xuất", pressed: true }),
      ).toBeVisible();
      if (fixture.workflowKey === "optimize_product_2") {
        // Card consumption was a property of the mock `ExecutionRecord` that
        // #1320 part 2 deleted. The replay path persists nothing -- ADR-094
        // decision 1 -- so there is no run to consume the card, and it stays
        // listed. That is consistent with the replay being a repeatable
        // demonstration rather than a real approval; real card consumption
        // (ADR-084 decision 6) is a server-side property of a real run and is
        // exercised by the signed-in path, not here.
        await expect(card).toHaveCount(1);
      } else {
        await expect(card).toHaveCount(0);
      }
    }
  });
});
