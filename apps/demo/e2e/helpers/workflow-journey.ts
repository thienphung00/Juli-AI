import { expect, type Page } from "@playwright/test";

export async function advanceReviewToApproveStage(page: Page) {
  let guard = 0;

  while (guard < 12) {
    const approve = page.getByRole("button", { name: "Phê duyệt" }).last();
    if (await approve.isVisible()) {
      await expect(approve).toBeVisible();
      return;
    }

    const next = page.getByRole("button", { name: "Tiếp theo" });
    await expect(next).toBeVisible();
    await next.click({ force: true });
    guard += 1;
  }

  await expect(
    page.getByRole("button", { name: "Phê duyệt" }).last(),
  ).toBeVisible();
}

export async function approveFromRecommendations(
  page: Page,
  workflowKey: string,
  title: string,
) {
  await page.goto("/decisions");
  const card = page.locator(`article[data-workflow-key="${workflowKey}"]`);
  await expect(card).toBeVisible();
  await expect(card.getByRole("heading", { level: 3, name: title })).toBeVisible();
  await card.getByRole("button", { name: "Phê duyệt" }).click();
  await expect(page).toHaveURL(
    new RegExp(`/decisions/recommendations/${workflowKey}$`),
  );
  await advanceReviewToApproveStage(page);
  await page.getByRole("button", { name: "Phê duyệt" }).last().click();
  await expect(page).toHaveURL(/\/decisions\/in-progress\//);
}

export async function resetDemo(page: Page) {
  await page.getByRole("button", { name: "Làm mới Demo" }).click();
  await expect(page).toHaveURL(/\/decisions$/);
}
