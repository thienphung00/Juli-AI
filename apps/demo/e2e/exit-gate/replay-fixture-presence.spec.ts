import { expect, test } from "@playwright/test";

import {
  REPLAY_SCENARIO_PRODUCT_NAME,
  REPLAY_SCENARIO_PROPOSED_TITLE,
  REPLAY_SCENARIO_RUN_ID,
} from "../fixtures/replay-scenario";

/**
 * Issue #1321 acceptance criterion: "the journey fails loudly if the
 * scenario fixture is missing from the built artifact, rather than
 * skipping" (release-evidence-plan-issue-1321.json `journeys[2]`,
 * "fixture-absence-fails-loudly").
 *
 * `apps/demo/scripts/verify-replay-scenario-in-build.mjs` already asserts
 * this at BUILD time by scanning `.next/` for the scenario's own
 * `scenario_id` marker (wired into `pnpm build`, so it already runs on
 * every path that builds, including `pnpm check:demo`). This spec is the
 * deliberate second, independent layer the release-evidence-plan's
 * `staticAssetChecks` names: a browser-level check against whatever the
 * suite is ACTUALLY running against (`DEMO_E2E_ARTIFACT_DIR` in
 * `playwright.config.ts` points this at the release candidate artifact in
 * CI) rather than the build step that produced it — catching, for
 * example, a candidate artifact that was built correctly but staged or
 * served incorrectly, which the build-time check alone cannot see.
 *
 * Both assertions below are hard `expect(...)` calls — no `test.skip()`
 * anywhere in this file. A missing scenario fails this test loudly.
 */
test.describe("Replay scenario fixture — present in the artifact under test (issue #1321)", () => {
  test("the run route renders the captured scenario's real content, never an idle/empty run", async ({
    page,
  }) => {
    await page.goto(`/decisions/in-progress/${REPLAY_SCENARIO_RUN_ID}`);

    // If the scenario JSON were absent from the bundle,
    // `getReplayInitialEvents()` would have thrown at module load
    // (`replay-scenario.ts`'s own "absence must fail loudly" guard) and
    // this component tree would never render a tablist at all — so this
    // is a real, hard assertion, not an incidental one.
    await expect(page.getByRole("tablist", { name: "Các bước xử lý" })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(REPLAY_SCENARIO_PRODUCT_NAME).first()).toBeVisible();
    await expect(page.getByText(REPLAY_SCENARIO_PROPOSED_TITLE).first()).toBeVisible();
  });

  test("the scenario's own unique marker is present in a served JS asset (build-output-level, not source-tree)", async ({
    page,
    request,
  }) => {
    const scriptSources: string[] = [];
    page.on("response", (response) => {
      if (
        response.request().resourceType() === "script" &&
        response.url().includes("/_next/")
      ) {
        scriptSources.push(response.url());
      }
    });

    await page.goto(`/decisions/in-progress/${REPLAY_SCENARIO_RUN_ID}`);
    await expect(page.getByRole("tablist")).toBeVisible({ timeout: 15_000 });

    expect(
      scriptSources.length,
      "discovered zero /_next/ script assets to scan — the page did not load any client JS at all",
    ).toBeGreaterThan(0);

    // The scenario's own scenario_id — the same marker
    // `verify-replay-scenario-in-build.mjs` scans `.next/` for at build
    // time, re-checked here against whatever bytes the running server (the
    // candidate artifact in CI) actually served.
    const marker = "optimize-product-confirm-pause";
    let found = false;
    for (const url of scriptSources) {
      const response = await request.get(url);
      if (!response.ok()) continue;
      const body = await response.text();
      if (body.includes(marker)) {
        found = true;
        break;
      }
    }

    expect(
      found,
      `the replay scenario marker "${marker}" was not found in any served /_next/ script — ` +
        "the fixture is missing from what this suite is actually running against",
    ).toBe(true);
  });
});
