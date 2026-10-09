import { expect, test } from "@playwright/test";

import { DEMO_MODE_REPLAY_LABEL } from "../../src/lib/demo-mode-copy";
import { JULI_LOCKED_HINT } from "../../src/lib/app-navigation";
import {
  HOME_MATRIX_REGION,
  enterReplayDemo,
  expectFourDestinationShell,
  expectShopHeader,
  navigatePrimaryDestination,
  openShopMenu,
} from "../helpers/demo-navigation";

// AC-8.5 retired the contextual-assistance aside (ADR-109 d.1: the shell
// follows the sales demo video, which has none). What this suite still
// guards on every destination is the shell itself: the four-item nav with
// Juli locked, and the shop header without a global stepper.
const DESTINATION_PATHS = [
  { path: "/", label: "Trang chủ" },
  { path: "/decisions", label: "Quyết định" },
  { path: "/analytics", label: "Phân tích" },
] as const;

test.describe("Phase 2.6 exit gate — locale and truthful states", () => {
  test("Vietnamese diacritics appear on Home and Decisions", async ({ page }) => {
    await enterReplayDemo(page);
    const matrix = page.getByRole("region", { name: HOME_MATRIX_REGION });
    await expect(matrix.getByText("Tăng trưởng từ sản phẩm")).toBeVisible();
    await expect(matrix.getByText("Tăng trưởng từ nội dung")).toBeVisible();
    await expect(page.getByTestId("shop-header")).toContainText("Cửa hàng Mẫu Hoa Mai");

    await page.goto("/decisions");
    await expect(page.getByRole("button", { name: "Đề xuất" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Đang thực hiện" })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Danh mục chăm sóc da", level: 3 }),
    ).toBeVisible();
    await expect(
      page
        .locator('article[data-workflow-key="create_hero_product_1"]')
        .getByText("Tạo sản phẩm nổi bật"),
    ).toBeVisible();
  });

  // "Mock mode notice" is this test's coverage name for the
  // `mock-data-notice` testid asserted below — the phase-2.6 exit gate
  // (tests/unit/test_phase_2_6_demo_exit_gate.py) greps this file's source
  // for it to prove the concern stays covered. Sellers never see the word:
  // the header badge renders DEMO_MODE_REPLAY_LABEL ("Bản minh họa", #1907).
  test("Mock mode notice stays truthful, and sign-in is a real door out rather than a dead link back to /", async ({
    page,
  }) => {
    // #1319 retired the "coming soon" Sign-in stub -- an affordance that
    // looked like a control and did nothing. #1907 retired its replacement
    // too: a `Đăng nhập` link back to `/` was a second dead control for any
    // visitor who had already entered the replay demo, because `/`
    // short-circuits straight back to Home. The header control is now a
    // full-page link to Supabase Auth; landing-doors.spec.ts owns the
    // exhaustive reachability coverage, so this only asserts the truthful
    // states this suite has always guarded.
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

    await enterReplayDemo(page);
    await expect(page.getByTestId("mock-data-notice")).toBeVisible();
    // The label is the same constant DemoShell renders (dictionary.md
    // `demo.mode.replay`), so this spec cannot drift from the component;
    // demo-shell.test.tsx pins the literal Vietnamese against the dictionary.
    await expect(page.getByTestId("shop-header")).toContainText(DEMO_MODE_REPLAY_LABEL);

    // AC-8.5: Đăng nhập lives in the shop-avatar menu.
    await openShopMenu(page);
    const signIn = page.getByRole("link", { name: "Đăng nhập với Google", exact: true });
    await expect(signIn).not.toHaveAttribute("href", "/");
    await expect(signIn).toHaveAttribute("href", /\.supabase\.co/);

    // ADR-094 decision 1: entering and browsing the replay demo issues no
    // external request. The Supabase href above is a door, not a call site
    // -- nothing leaves the origin until the visitor chooses to walk out.
    expect(requests).toEqual([]);
  });

  test("Decisions error empty state exposes retry without fabricated data", async ({
    page,
  }) => {
    await page.goto("/decisions?load=error");
    await expect(
      page.getByRole("alert", { name: "Lỗi tải đề xuất" }),
    ).toContainText("Không thể tải đề xuất mẫu");
    await page.getByRole("button", { name: "Thử lại" }).click();
    await expect(
      page.getByRole("heading", { name: "Danh mục chăm sóc da", level: 3 }),
    ).toBeVisible();
    await expect(
      page
        .locator('article[data-workflow-key="create_hero_product_1"]')
        .getByText("Tạo sản phẩm nổi bật"),
    ).toBeVisible();
  });
});

test.describe("App shell regression (AC-8.5) — every destination", () => {
  for (const destination of DESTINATION_PATHS) {
    test(`${destination.label} keeps the rail and the shop header`, async ({ page }) => {
      await page.goto(destination.path);
      await expectFourDestinationShell(page);
      await expectShopHeader(page);
    });
  }

  test("Juli is shown, locked, and says what is coming", async ({ page }) => {
    await page.goto("/decisions");
    const juli = page
      .getByRole("navigation", { name: "Điều hướng chính" })
      .getByRole("link", { name: "Juli", exact: true });
    await expect(juli).toBeVisible();
    await expect(juli).toHaveAttribute("aria-disabled", "true");
    await expect(juli).toHaveAttribute("title", JULI_LOCKED_HINT);
    await juli.click({ force: true });
    await expect(page).toHaveURL(/\/decisions$/);
  });

  test("Cài đặt opens from the shop-avatar menu", async ({ page }) => {
    await page.goto("/decisions");
    await openShopMenu(page);
    await page.getByRole("link", { name: "Cài đặt" }).click();
    await expect(page).toHaveURL(/\/settings$/);
    await expectFourDestinationShell(page);
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
