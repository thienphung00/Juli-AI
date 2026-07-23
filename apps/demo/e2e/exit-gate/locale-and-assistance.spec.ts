import { expect, test } from "@playwright/test";

import {
  expectContextualAssistance,
  expectFourDestinationShell,
  navigatePrimaryDestination,
} from "../helpers/demo-navigation";

const DESTINATION_PATHS = [
  { path: "/", assistanceEyebrow: "Trang chủ" },
  { path: "/decisions", assistanceEyebrow: "Quyết định" },
  { path: "/analytics", assistanceEyebrow: "Phân tích" },
  { path: "/settings", assistanceEyebrow: "Cài đặt" },
] as const;

test.describe("Phase 2.6 exit gate — locale and truthful states", () => {
  test("Vietnamese diacritics appear on Home and Decisions", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Quyết định")).toBeVisible();
    await expect(page.getByText("Phân tích")).toBeVisible();
    await expect(page.getByText("Juli Demo Shop")).toBeVisible();

    await page.goto("/decisions");
    await expect(page.getByText("Đề xuất")).toBeVisible();
    await expect(page.getByText("Đang thực hiện")).toBeVisible();
    await expect(page.getByText("Tạo sản phẩm nổi bật")).toBeVisible();
  });

  test("Mock mode notice and Sign-in stub stay truthful", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("mock-data-notice")).toBeVisible();
    await expect(page.getByRole("button", { name: "Mock" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const signIn = page.getByRole("button", { name: "Sign-in" });
    await expect(signIn).toHaveAttribute("aria-disabled", "true");

    const requests: string[] = [];
    page.on("request", (request) => {
      const url = request.url();
      if (
        !url.startsWith("http://127.0.0.1") &&
        !url.startsWith("http://localhost")
      ) {
        requests.push(url);
      }
    });

    await signIn.click({ force: true });
    await expect(page).toHaveURL("/");
    expect(requests).toEqual([]);
  });

  test("Decisions error empty state exposes retry without fabricated data", async ({
    page,
  }) => {
    await page.goto("/decisions?load=error");
    await expect(page.getByRole("alert")).toContainText(
      "Không thể tải đề xuất mẫu",
    );
    await page.getByRole("button", { name: "Thử lại" }).click();
    await expect(page.getByText("Tạo sản phẩm nổi bật")).toBeVisible();
  });
});

test.describe("Phase 2.6 exit gate — contextual assistance regression", () => {
  for (const destination of DESTINATION_PATHS) {
    test(`${destination.assistanceEyebrow} provides grounded assistance`, async ({
      page,
    }) => {
      await page.goto(destination.path);
      await expectFourDestinationShell(page);
      await expectContextualAssistance(page);
      await expect(page.getByText(destination.assistanceEyebrow).first()).toBeVisible();
      await expect(
        page.getByRole("navigation", { name: "Điều hướng chính" }),
      ).not.toContainText("Juli");
    });
  }

  test("assistance cannot approve, reject, or execute", async ({ page }) => {
    await page.goto("/decisions");
    const assistance = page.locator(".demo-assistance");
    await expect(assistance.getByRole("button", { name: "Phê duyệt" })).toHaveCount(
      0,
    );
    await expect(assistance.getByRole("button", { name: "Từ chối" })).toHaveCount(
      0,
    );
  });

  test("primary navigation has exactly four destinations (no fifth tab)", async ({
    page,
  }) => {
    await page.goto("/");
    await expectFourDestinationShell(page);
    await navigatePrimaryDestination(page, "Phân tích");
    await expect(page).toHaveURL(/\/analytics/);
    await expectFourDestinationShell(page);
  });
});
