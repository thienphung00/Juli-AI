import { expect, type Page } from "@playwright/test";

/**
 * The four destinations of ADR-109 decision 7 (AC-8.5). Juli is shown but
 * locked: it keeps `role="link"` (so it is announced with the others) and
 * `aria-disabled="true"`, and has no href. Cài đặt is no longer a
 * destination — it lives in the shop-avatar menu (`openShopMenu`).
 */
const PRIMARY_DESTINATIONS = [
  "Trang chủ",
  "Quyết định",
  "Phân tích",
  "Juli",
] as const;

type NavigableDestination = "Trang chủ" | "Quyết định" | "Phân tích";

/** The sample Home's 5-stream matrix — what "Dùng thử Demo" reveals since AC-8.5. */
export const HOME_MATRIX_REGION = "Ma trận 5 luồng truy cập";

/**
 * Enter the demo through the replay door and land on Home.
 *
 * `/` stopped being the demo Home in #1319 — it is the two-door landing gate
 * (Dùng thử Demo / Đăng nhập với Google), and Home lives behind the replay
 * door. Since AC-8.5 that Home is the sample shop's overview (cards + the
 * 5-stream matrix), not two launcher cards.
 */
export async function enterReplayDemo(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Dùng thử Demo" }).click();
  await expect(page.getByRole("region", { name: HOME_MATRIX_REGION })).toBeVisible();
}

export async function expectFourDestinationShell(page: Page) {
  const navigation = page.getByRole("navigation", {
    name: "Điều hướng chính",
  });
  await expect(navigation).toBeVisible();
  const items = navigation.getByRole("link");
  await expect(items).toHaveCount(4);
  await expect(items).toHaveText([...PRIMARY_DESTINATIONS].map((label) => new RegExp(`^${label}`)));

  const juli = navigation.getByRole("link", { name: "Juli", exact: true });
  await expect(juli).toHaveAttribute("aria-disabled", "true");
  expect(await juli.getAttribute("href")).toBeNull();
  await expect(navigation).not.toContainText("Cài đặt");
}

/** The shop header: avatar menu button, no global stepper (ADR-109 d.8). */
export async function expectShopHeader(page: Page) {
  const header = page.getByTestId("shop-header");
  await expect(header).toBeVisible();
  await expect(header.getByRole("button", { name: /^Menu shop/ })).toBeVisible();
  await expect(header).toContainText("TikTok Shop");
  await expect(header).not.toContainText("Đo lường");
}

export async function openShopMenu(page: Page) {
  const avatar = page.getByRole("button", { name: /^Menu shop/ });
  if ((await avatar.getAttribute("aria-expanded")) !== "true") {
    await avatar.click();
  }
  await expect(avatar).toHaveAttribute("aria-expanded", "true");
}

export async function navigatePrimaryDestination(
  page: Page,
  label: NavigableDestination,
) {
  const link = page
    .getByRole("navigation", { name: "Điều hướng chính" })
    .getByRole("link", { name: label, exact: true });
  await link.scrollIntoViewIfNeeded();
  await link.click();
}
