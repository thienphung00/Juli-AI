import { expect, type Page } from "@playwright/test";

export async function advanceReviewToApproveStage(page: Page) {
  const approve = page.getByRole("button", { name: "Phê duyệt" }).last();
  let guard = 0;

  while (!(await approve.isVisible()) && guard < 12) {
    const next = page.getByRole("button", { name: "Tiếp theo" });
    await expect(next).toBeVisible();
    await next.scrollIntoViewIfNeeded();
    await next.click({ force: true });
    guard += 1;
  }

  await expect(approve).toBeVisible();
  await approve.scrollIntoViewIfNeeded();
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
