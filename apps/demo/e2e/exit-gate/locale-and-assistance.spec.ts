import { expect, test } from "@playwright/test";

import { DEMO_MODE_REPLAY_LABEL } from "../../src/lib/demo-mode-copy";
import {
  enterReplayDemo,
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
    await enterReplayDemo(page);
    const launchers = page.getByRole("region", { name: "Điểm đến chính" });
    await expect(
      launchers.getByRole("link", { name: /Quyết định/ }),
    ).toBeVisible();
    await expect(
      launchers.getByRole("link", { name: /Phân tích/ }),
    ).toBeVisible();
    await expect(page.getByText("Juli Demo Shop")).toBeVisible();

    await page.goto("/decisions");
    await expect(page.getByRole("button", { name: "Đề xuất" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Đang thực hiện" })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Tạo sản phẩm nổi bật", level: 3 }),
    ).toBeVisible();
  });

  test("Replay mode notice stays truthful, and sign-in is a real door out rather than a dead link back to /", async ({
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
    await expect(
      page.getByRole("button", { name: DEMO_MODE_REPLAY_LABEL }),
    ).toHaveAttribute("aria-pressed", "true");

    const signIn = page.getByRole("link", { name: "Đăng nhập" });
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
      page.getByRole("heading", { name: "Tạo sản phẩm nổi bật", level: 3 }),
    ).toBeVisible();
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
