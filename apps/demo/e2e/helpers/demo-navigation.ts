import { expect, type Page } from "@playwright/test";

const PRIMARY_DESTINATIONS = [
  "Trang chủ",
  "Quyết định",
  "Phân tích",
  "Cài đặt",
] as const;

export async function expectFourDestinationShell(page: Page) {
  const navigation = page.getByRole("navigation", {
    name: "Điều hướng chính",
  });
  const links = navigation.getByRole("link");
  await expect(links).toHaveCount(4);

  for (const label of PRIMARY_DESTINATIONS) {
    await expect(
      navigation.getByRole("link", { name: new RegExp(label, "i") }),
    ).toBeVisible();
  }
}

export async function expectContextualAssistance(page: Page) {
  await expect(page.getByRole("heading", { name: "Gợi ý từ Juli" })).toBeVisible();
  await expect(
    page.getByText(
      "Juli chỉ giải thích trong ngữ cảnh này. Mọi quyết định và thao tác vẫn do bạn kiểm soát.",
    ),
  ).toBeVisible();
}

export async function navigatePrimaryDestination(
  page: Page,
  label: (typeof PRIMARY_DESTINATIONS)[number],
) {
  const link = page
    .getByRole("navigation", { name: "Điều hướng chính" })
    .getByRole("link", { name: new RegExp(label, "i") });
  await link.scrollIntoViewIfNeeded();
  await link.click({ force: true });
}
