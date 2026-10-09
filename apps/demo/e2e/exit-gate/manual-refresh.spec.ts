import { expect, test } from "@playwright/test";

import { resetDemo } from "../helpers/workflow-journey";

/**
 * "Làm mới Demo" puts the signed-out Quyết định back: since P11 that page is
 * the P10 sample over an in-memory store, remounted on the reset.
 */
const sampleCard = (page: import("@playwright/test").Page, name: string) =>
  page.getByTestId("recommendation-card").filter({ hasText: name });

async function rejectCard(page: import("@playwright/test").Page, name: string) {
  const card = sampleCard(page, name);
  await card.getByRole("button", { name: "Từ chối" }).click();
  const dialog = page.getByRole("dialog", { name: "Từ chối thẻ này?" });
  await dialog.getByRole("radio").first().check();
  await dialog.getByRole("button", { name: "Từ chối thẻ" }).click();
  await expect(card.getByTestId("card-status")).toHaveText("Đã từ chối");
}

test.describe("Phase 2.6 exit gate — Manual Refresh", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/decisions");
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
    await page.reload();
  });

  test("resets mutated Decisions state and returns to Recommendations (Đề xuất)", async ({ page }) => {
    await rejectCard(page, "Son môi số 12");

    await resetDemo(page);

    await expect(page.getByRole("tab", { name: "Đề xuất" })).toHaveAttribute("aria-selected", "true");
    await expect(sampleCard(page, "Son môi số 12").getByTestId("card-status")).toHaveText("Chờ duyệt");
  });

  test("from Home, refresh returns to Decisions Đề xuất with every card pending again", async ({ page }) => {
    await rejectCard(page, "Mặt nạ đất sét 100g");
    await page.goto("/");
    await resetDemo(page);
    await expect(page).toHaveURL(/\/decisions$/);
    await expect(sampleCard(page, "Mặt nạ đất sét 100g").getByTestId("card-status")).toHaveText("Chờ duyệt");
  });
});
