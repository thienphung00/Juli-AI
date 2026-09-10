import { expect, test } from "@playwright/test";

/**
 * Issue #1905's decisive acceptance criterion -- the one #1319 lacked, and
 * lacking it is exactly how a dead door shipped and stayed shipped: assert
 * against the ARTIFACT under test (this suite's `webServer` starts whatever
 * `DEMO_E2E_ARTIFACT_DIR` points at unchanged, per playwright.config.ts --
 * the same mechanism `release.yml`'s "Browser-level checks against the
 * artifact" step already uses) that the "Đăng nhập với Google" control is a
 * real <a> whose href origin is a Supabase project host, never a
 * `<span role="link">`. `demo-landing.test.tsx` covers the component's
 * branching logic in jsdom -- that alone is precisely how #1319 shipped
 * while its own criterion "passed": the release-evidence-plan's
 * `doNotInfer` names this explicitly. This is the second, independent
 * layer: a real browser against whatever bytes were actually built.
 *
 * THIS TEST IS EXPECTED TO FAIL against any artifact built without
 * NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY set at build
 * time -- which, as of this change, is every local run and every CI run
 * until the owner adds the two repository secrets. That failure is the
 * defect this issue exists to make visible, not a flake to route around.
 */
test.describe("Landing doors — the Google door is a real link in the artifact, not a disabled stub (issue #1905)", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
    await page.reload();
  });

  test("the Google control is an <a> with an href whose origin is a Supabase project host", async ({
    page,
  }) => {
    const link = page.getByRole("link", { name: "Đăng nhập với Google" });
    await expect(link).toBeVisible();

    // A build without the env renders role="link" on a <span> -- the
    // honest-disabled branch demo-landing.tsx keeps on purpose (never
    // deleted as dead code). getByRole cannot distinguish the two; tagName
    // is what tells them apart.
    const tagName = await link.evaluate((el) => el.tagName);
    expect(
      tagName,
      'the Google door rendered as a <span>, not an <a> -- this artifact was built without a working NEXT_PUBLIC_SUPABASE_URL/NEXT_PUBLIC_SUPABASE_ANON_KEY. See infra/scripts/env/demo.env.example and the "Build release artifact" step in .github/workflows/release.yml.',
    ).toBe("A");

    const href = await link.getAttribute("href");
    expect(
      href,
      "the <a> has no href -- the artifact was not built with Supabase env configured",
    ).toBeTruthy();

    const hostname = new URL(href!).hostname;
    expect(
      hostname,
      `href origin "${hostname}" is not a Supabase project host`,
    ).toMatch(/\.supabase\.co$/);
  });

  test("clicking the Google control targets a full-page navigation off the demo origin", async ({
    page,
  }) => {
    const link = page.getByRole("link", { name: "Đăng nhập với Google" });
    await expect(link).toBeVisible();

    const href = await link.getAttribute("href");
    expect(href).toBeTruthy();

    // Asserted by the href's own origin rather than by actually clicking
    // through -- this suite cannot authenticate against Google's real
    // consent screen, and the release-evidence-plan's candidate journey
    // only requires observing that the navigation targets off-origin.
    const targetOrigin = new URL(href!).origin;
    const currentOrigin = new URL(page.url()).origin;
    expect(targetOrigin).not.toBe(currentOrigin);
  });
});
