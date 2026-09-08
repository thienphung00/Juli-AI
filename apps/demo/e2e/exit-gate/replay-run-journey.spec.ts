import { expect, test } from "@playwright/test";

import {
  CONFIRMATION_DECISION_URL_PATTERN,
  REPLAY_SCENARIO_CLOCK_PIN,
  REPLAY_SCENARIO_PRODUCT_NAME,
  REPLAY_SCENARIO_PROPOSED_TITLE,
  REPLAY_SCENARIO_RUN_ID,
  REPLAY_SCENARIO_WORKFLOW_KEY,
  REPLAY_SCENARIO_WORKFLOW_TITLE,
} from "../fixtures/replay-scenario";

/**
 * Issue #1321 (ADR-076 decision 7, PUI-DESIGN.md §9) — the deterministic
 * replay-based journey: Dùng thử Demo → Decisions → approve → the staged
 * run view → the stages advance → pick an option → confirm → completion.
 * Deterministic because it is replay: no model, no marketplace, no
 * external network (release-evidence-plan-issue-1321.json).
 *
 * `retries: 0` overrides `playwright.config.ts`'s CI-wide `retries: 2` for
 * THIS spec only — flakiness here is a specified failure, never something
 * a retry papers over (release-evidence-plan `doNotInfer`).
 *
 * ============================================================================
 * WHY THIS TEST IS CURRENTLY RED (as of 2026-09-08, branch
 * feature/issue-1321-replay-journey) — read before touching the
 * assertions below rather than weakening them.
 * ============================================================================
 *
 * This issue is filed "Blocked by #1317, #1319, #1320" and #1320's own
 * "Part 2" scope (added 2026-09-08) states plainly: "Taking Dùng thử Demo
 * and approving reaches the staged run view, and the stages advance...
 * That is the wiring #1752 deliberately stopped short of... left reaching
 * the view from an approval to this slice." That wiring does not exist on
 * this branch yet — verified directly (not inferred) against the running
 * build before writing this spec:
 *
 * 1. Clicking "Phê duyệt" on the "Tối ưu sản phẩm" card in Decisions still
 *    goes through the pre-existing five-stage mock review flow
 *    (`recommendations-panel.tsx` / `recommendation-review.tsx`) and never
 *    navigates to `/decisions/in-progress/{runId}` — `RunDetailRoute`
 *    (issue #1316/#1752) is reachable ONLY by a direct URL today. This is
 *    exactly, and only, #1320 part 2's stated remaining scope.
 *
 * 2. A second, deeper gap exists past that one: `ReplayRunDetail` (the
 *    anonymous/no-token branch of `run-detail-route.tsx`) renders
 *    `RunStagedView` with no `confirm` override and no `confirmationToken`,
 *    so `OptionPicker`'s default `confirm = submitConfirmationDecision`
 *    fires a REAL `POST /v1/demo/runs/{id}/confirmations/{toolCallId}` the
 *    instant a visitor clicks "Xác nhận phương án này" or "Không thực
 *    hiện" in replay mode — verified by a manual probe against this
 *    branch's build (request observed, then a 404 since no backend is
 *    running, then the generic "Không thể xác nhận lựa chọn này."
 *    rejection copy). This directly violates ADR-094 decision 1 ("no
 *    `/v1/*` request, ever") and #1320 part 2's own added criterion ("the
 *    stages advance... with no `/v1/*` request for the whole journey").
 *    Nothing in this branch wires a replay-local confirm (e.g. one that
 *    reads the golden scenario's own `continuations.approve` /
 *    `continuations.decline` and advances the reducer without a network
 *    round trip) — that wiring does not exist yet either.
 *
 * 3. A THIRD gap, independent of the above two: the captured scenario's
 *    `workflow.approval_required.expires_at` is a fixed absolute
 *    timestamp (`2026-08-28T12:32:13.308159Z`) that `rebaseEvent()`
 *    (`lib/run-surface/replay-scenario.ts`) never rebases (only the
 *    envelope's own `timestamp` field is shifted to "now" — the nested
 *    payload field is left as captured). Once real wall-clock time passes
 *    that date, the Đề xuất option picker renders permanently expired
 *    ("Đề xuất đã hết hiệu lực.") for every visitor, with no way to select
 *    an option at all. This is out of this issue's file boundary
 *    (`lib/run-surface/replay-scenario.ts` is production source, not an
 *    e2e spec/dictionary/MODULE.md/CI-config) — flagged in the
 *    implementation report for Meta/Architect to route, not silently
 *    patched here.
 *
 * 4. A FOURTH, structural gap: "a forced mid-run disconnect and reconnect
 *    is part of the journey" (issue text) describes a property built for
 *    the SIGNED-IN path's `useRunStream` (real SSE, real backoff/replay
 *    via `Last-Event-ID`). The anonymous replay path this journey is
 *    specified to run entirely inside has no stream to disconnect at
 *    all: `ReplayRunDetail` hardcodes `isReconnecting={false}` and
 *    `useReplayEvents` is pure `setTimeout` pacing with zero network
 *    dependency. There is currently no mechanism, anywhere in this
 *    codebase, for a "disconnect" to mean anything on the replay-only
 *    path this journey is scoped to. This looks like a genuine planning
 *    gap rather than something assignable to #1320 part 2's stated scope
 *    (which only names "no `/v1/*` request", not reconnect) — flagged
 *    for Meta/Architect rather than invented here.
 *
 * This spec exercises the REAL click path throughout — no direct-URL
 * shortcut past the missing approval→run-view navigation, no
 * `page.route()` fulfillment standing in for the missing replay-local
 * confirm handler, and no reduced assertion set. It is expected to fail at
 * the point documented in each `step()` call below, honestly, until the
 * blocking issues above are resolved. Once #1320 part 2 (and the two
 * follow-up gaps above) land, this test should be re-run and, if it goes
 * green end to end, is the CI-visible half of ADR-076's phase gate.
 */
test.describe("Replay journey — issue #1321 (ADR-076 decision 7)", () => {
  test.describe.configure({ retries: 0 });

  test.beforeEach(async ({ page }) => {
    // Pinned BEFORE the first navigation, per `REPLAY_SCENARIO_CLOCK_PIN`'s
    // own docstring: keeps this journey deterministic regardless of what
    // real calendar date it runs on, independent of the unrebased
    // `expires_at` gap this investigation also surfaced. The fake clock
    // starts paused — `page.clock.fastForward(...)` below advances it
    // exactly enough to fire the replay's own `setTimeout`-paced reveals,
    // deterministically, with no dependency on real wall-clock timing.
    await page.clock.install({ time: new Date(REPLAY_SCENARIO_CLOCK_PIN) });
    await page.goto("/");
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
    await page.reload();
  });

  test("Dùng thử Demo → Decisions → approve → staged run view → stages advance → pick an option → confirm → completion, with zero /v1/* requests and a mid-run disconnect/reconnect", async ({
    page,
  }) => {
    const v1Requests: string[] = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/v1/")) {
        v1Requests.push(`${request.method()} ${url.pathname}`);
      }
    });

    await test.step("Dùng thử Demo enters the replay — no auth, no session", async () => {
      await page
        .getByRole("button", { name: "Dùng thử Demo" })
        .click();
      await expect(
        page.getByRole("region", { name: "Điểm đến chính" }),
      ).toBeVisible();
    });

    await test.step("Home → Decisions", async () => {
      await page
        .getByRole("region", { name: "Điểm đến chính" })
        .getByRole("link", { name: /Quyết định/ })
        .click();
      await expect(page).toHaveURL(/\/decisions$/);
    });

    await test.step("approve the captured scenario's own recommendation", async () => {
      const card = page.locator(
        `article[data-workflow-key="${REPLAY_SCENARIO_WORKFLOW_KEY}"]`,
      );
      await expect(card).toBeVisible();
      await expect(
        card.getByRole("heading", { level: 3, name: REPLAY_SCENARIO_WORKFLOW_TITLE }),
      ).toBeVisible();
      await card.scrollIntoViewIfNeeded();
      await card.getByRole("button", { name: "Phê duyệt" }).click();

      // THE CURRENTLY-BLOCKED STEP (gap 1 above, #1320 part 2's stated
      // scope): approving this card must reach the captured run's staged
      // view, never the pre-existing five-stage mock review flow.
      await expect(page).toHaveURL(
        new RegExp(`/decisions/in-progress/${REPLAY_SCENARIO_RUN_ID}`),
      );
      await expect(page.getByRole("tablist", { name: "Các bước xử lý" })).toBeVisible();

      // Deterministically reveal the captured scenario's four initial
      // events (real captured inter-event deltas are on the order of 1-2ms
      // each) — see the clock-pin docstring in `beforeEach` above.
      await page.clock.fastForward(1000);
    });

    await test.step("stages advance: Phân tích/Thông tin sản phẩm/SEO frozen, Đề xuất active, Cập nhật/Hoàn tất locked", async () => {
      await expect(
        page.getByRole("tab", { name: /Phân tích.*Đã hoàn tất/ }),
      ).toBeVisible();
      await expect(
        page.getByRole("tab", { name: /Thông tin sản phẩm.*Đã hoàn tất/ }),
      ).toBeVisible();
      await expect(page.getByRole("tab", { name: /SEO.*Đã hoàn tất/ })).toBeVisible();
      await expect(page.getByRole("tab", { name: /Đề xuất.*Đang diễn ra/ })).toBeVisible();
      await expect(page.getByRole("tab", { name: /Cập nhật.*Chưa mở khoá/ })).toBeVisible();
      await expect(page.getByRole("tab", { name: /Hoàn tất.*Chưa mở khoá/ })).toBeVisible();
      await expect(page.getByText(REPLAY_SCENARIO_PRODUCT_NAME).first()).toBeVisible();
    });

    await test.step("pick the option → confirm asserts the request the client actually sent", async () => {
      const radio = page.getByRole("radio").first();
      await radio.click();
      await expect(radio).toHaveAttribute("aria-checked", "true");

      const confirmButton = page.getByRole("button", { name: "Xác nhận phương án này" });
      await expect(confirmButton).toBeEnabled();

      // No `page.route()` fulfillment here on purpose: a real replay must
      // never reach the network at all (ADR-094 decision 1). Faking a
      // response would be exactly the "stub past the gap" this journey is
      // written not to do — the confirmation client's own docstring names
      // the property this asserts: "selecting A then B then confirming
      // sends B is a property of the CALLER holding one piece of state,"
      // and a UI that looks armed on the wrong option must fail here.
      await confirmButton.click();

      // Advances the fake clock generously past any reasonable pacing a
      // future replay-local confirm handler might use to reveal the
      // continuation events (matching the realism pacing PUI-DESIGN.md §1
      // already specifies for the initial reveal) — bounded and explicit
      // rather than depending on real wall-clock timing.
      await page.clock.fastForward(10_000);
    });

    await test.step("forced mid-run disconnect and reconnect — never renders as a run failure", async () => {
      // Deliberately not comparing a stage-content snapshot before/after:
      // the canvas legitimately auto-follows the live edge as the run
      // advances (`RunStagedView`'s `pinnedToLiveEdge` derivation), so
      // "identical text before and after" would be the WRONG bar here — a
      // run that keeps progressing during the interruption should keep
      // progressing. The actual property (PUI-DESIGN.md §8): a dropped
      // transport is never rendered as the run itself having failed, and
      // the run reaches the same correct terminal state either way (the
      // "completion" step below is the equality check, over the eventual
      // state rather than a mid-flight snapshot).
      await page.context().setOffline(true);
      await page.waitForTimeout(1000);
      await expect(page.getByRole("alert")).toHaveCount(0);
      const statusRegion = page.getByRole("status");
      if (await statusRegion.count()) {
        await expect(statusRegion.first()).not.toContainText(/lỗi|thất bại|gặp sự cố/i);
      }
      await page.context().setOffline(false);
    });

    await test.step("completion — the run reaches Hoàn tất with the approved outcome, never the decline or rejection copy", async () => {
      await expect(
        page.getByText("Juli đã hoàn tất và áp dụng thay đổi được phê duyệt."),
      ).toBeVisible({ timeout: 15_000 });
      // A finished run opens/renders with every reached stage frozen, the
      // terminal stage included — `RunStagedView`'s own "finished runs
      // open ... with all stages frozen" contract, never "active" once
      // `view.terminal` is set.
      await expect(
        page.getByRole("tab", { name: /Hoàn tất.*Đã hoàn tất/ }),
      ).toBeVisible();
      await expect(page.getByText("Bạn đã chọn không thay đổi giá")).not.toBeVisible();
      await expect(page.getByText("Không thể xác nhận lựa chọn này.")).not.toBeVisible();

      // The specific option's effect actually landed — reachable via the
      // now-frozen (clickable) Cập nhật stepper node, timing-independent
      // of whether continuation events were paced or applied in one shot.
      await page.getByRole("tab", { name: /Cập nhật/ }).click();
      await expect(page.getByText(REPLAY_SCENARIO_PROPOSED_TITLE)).toBeVisible();
    });

    await test.step("zero /v1/* requests for the whole journey (ADR-094 decision 1)", async () => {
      expect(v1Requests, "the replay journey must issue no /v1/* request at all").toEqual([]);
    });
  });

  // Independent of the full journey above: a defense-in-depth check that
  // the exact confirmation route this journey must never reach is named
  // precisely, not just "any /v1/* request" — kept as its own assertion so
  // a future change that narrows the /v1/* sweep above still catches this
  // one specifically.
  test("the confirmation decision route is never requested from the replay door", async ({ page }) => {
    const confirmationRequests: string[] = [];
    page.on("request", (request) => {
      if (CONFIRMATION_DECISION_URL_PATTERN.test(request.url())) {
        confirmationRequests.push(request.url());
      }
    });

    await page.goto(`/decisions/in-progress/${REPLAY_SCENARIO_RUN_ID}`);
    await page.waitForTimeout(2000);

    expect(confirmationRequests).toEqual([]);
  });
});
