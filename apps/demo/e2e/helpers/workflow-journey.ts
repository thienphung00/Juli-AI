import { expect, type Page } from "@playwright/test";

export async function advanceReviewToApproveStage(page: Page) {
  const reviewActions = page.locator(".demo-review__actions");
  await expect(reviewActions).toBeVisible();

  for (let guard = 0; guard < 12; guard += 1) {
    const approve = reviewActions.getByRole("button", { name: "Phê duyệt" });
    if (await approve.isVisible()) {
      await expect(approve).toBeVisible();
      return;
    }

    const next = reviewActions.getByRole("button", { name: "Tiếp theo" });
    if (await next.isVisible()) {
      await next.click();
      await expect(reviewActions).toBeVisible();
      continue;
    }

    await expect(
      reviewActions.getByRole("button", { name: /Tiếp theo|Phê duyệt/ }),
    ).toBeVisible();
  }

  await expect(
    reviewActions.getByRole("button", { name: "Phê duyệt" }),
  ).toBeVisible();
}

/** Open Approve-stage ConfirmDialog and confirm (DVR-A5 gate). */
export async function confirmApproveThroughGate(page: Page) {
  await page
    .locator(".demo-review__actions")
    .getByRole("button", { name: "Phê duyệt" })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByRole("heading", { name: "Xác nhận phê duyệt" }),
  ).toBeVisible();
  await dialog.getByRole("button", { name: "Phê duyệt" }).click();
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
  await card.scrollIntoViewIfNeeded();
  await Promise.all([
    page.waitForURL(new RegExp(`/decisions/recommendations/${workflowKey}$`)),
    card.getByRole("button", { name: "Phê duyệt" }).click(),
  ]);
  await advanceReviewToApproveStage(page);
  await confirmApproveThroughGate(page);
  await expect(page).toHaveURL(/\/decisions\/in-progress\//);
}

export async function resetDemo(page: Page) {
  await page.getByRole("button", { name: "Làm mới Demo" }).click();
  await expect(page).toHaveURL(/\/decisions$/);
}
