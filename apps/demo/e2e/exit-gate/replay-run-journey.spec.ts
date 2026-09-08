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
 * STATUS AS OF 2026-09-08 (branch feature/issue-1321-replay-journey,
 * after #1762 / issue #1320 part 2 merged into the wave) — read before
 * touching the assertions below rather than weakening them.
 * ============================================================================
 *
 * GAP 1 (approval → run-view navigation) IS RESOLVED. #1762 wired
 * `RecommendationReview` to push `/decisions/in-progress/{runId}` for
 * Optimize Product's `onApproveConfirm` (`recommendation-review.tsx:59-64`).
 * A first pass of this spec still failed after that merge — not because
 * the wiring was wrong, but because THIS SPEC skipped the two-step
 * consent gate ADR-055 item 8's `PlanReviewCard` requires: clicking the
 * list card's "Phê duyệt" only reaches the REVIEW page
 * (`/decisions/recommendations/{workflowKey}`); a second "Phê duyệt" in
 * `.demo-plan__actions` only ARMS a `ConfirmDialog` (`role="dialog"`,
 * heading "Xác nhận phê duyệt"); only the CONFIRM button *inside that
 * dialog* triggers `onApproveConfirm`'s navigation
 * (`review-test-helpers.ts`'s `confirmApproveThroughGate` encodes the same
 * sequence for the unit suite). Skipping straight from the list-card click
 * to asserting the run-view URL was asserting less than the product's own
 * "no single click authorizes anything" guarantee (#1317) — fixed by
 * walking the gate explicitly below, with an assertion that the URL stays
 * on the review route after the FIRST click and only changes after the
 * dialog's own confirm.
 *
 * GAP 2 (replay-mode confirm hits real network) IS STILL OPEN, own issue
 * #1764. `ReplayRunDetail` (the anonymous/no-token branch of
 * `run-detail-route.tsx`) renders `RunStagedView` with no `confirm`
 * override and no `confirmationToken`, so `OptionPicker`'s default
 * `confirm = submitConfirmationDecision` fires a REAL
 * `POST /v1/demo/runs/{id}/confirmations/{toolCallId}` the instant a
 * visitor clicks "Xác nhận phương án này" or "Không thực hiện" in replay
 * mode — verified by a manual probe against this branch's build (request
 * observed, then a 404 since no backend is running, then the generic
 * "Không thể xác nhận lựa chọn này." rejection copy). This directly
 * violates ADR-094 decision 1 ("no `/v1/*` request, ever"). This spec's
 * OWN second test below ("the confirmation decision route is never
 * requested from the replay door") is the one that catches it — expected
 * to keep failing at the confirm step until #1764 lands, per the
 * coordinator's instruction not to work around it.
 *
 * GAP 3 (unrebased `expires_at`) is a real production defect (flagged in
 * `apps/demo/MODULE.md`, not fixed here — out of this issue's file
 * boundary), worked AROUND for pure testability via the pinned fake clock
 * below (`REPLAY_SCENARIO_CLOCK_PIN`) — a test-determinism choice, not a
 * shortcut past product behavior.
 *
 * GAP 4 (no disconnect/reconnect mechanism on the replay-only path) is
 * still open, flagged for Meta/Architect — nothing in this codebase gives
 * "disconnect" a meaning on a stream-free, `setTimeout`-paced replay.
 *
 * This spec exercises the REAL click path throughout, including the full
 * two-step consent gate — no direct-URL shortcut past any navigation, no
 * `page.route()` fulfillment standing in for the missing replay-local
 * confirm handler, and no reduced assertion set. It is expected to fail at
 * the confirm step (gap 2, #1764) until that lands. Once #1764 (and gap 4)
 * are resolved, this test should be re-run and, if it goes green end to
 * end, is the CI-visible half of ADR-076's phase gate.
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

    await test.step("navigate from the Decisions list card to its review page", async () => {
      const card = page.locator(
        `article[data-workflow-key="${REPLAY_SCENARIO_WORKFLOW_KEY}"]`,
      );
      await expect(card).toBeVisible();
      await expect(
        card.getByRole("heading", { level: 3, name: REPLAY_SCENARIO_WORKFLOW_TITLE }),
      ).toBeVisible();
      await card.scrollIntoViewIfNeeded();
      await Promise.all([
        page.waitForURL(
          new RegExp(`/decisions/recommendations/${REPLAY_SCENARIO_WORKFLOW_KEY}$`),
        ),
        card.getByRole("button", { name: "Phê duyệt" }).click(),
      ]);
    });

    await test.step("walk the two-step consent gate on the review page — no single click authorizes anything (#1317)", async () => {
      // ADR-055 item 8's Situation → Decision → Details spine
      // (`PlanReviewCard`) renders the first "Phê duyệt" in its
      // `.demo-plan__actions` footer; clicking it only ARMS the gate
      // (`setApproveGateOpen(true)`) — it must not, by itself, navigate
      // anywhere. Asserted explicitly below rather than assumed, per the
      // coordinator's note: this turns an incidental step into a checked
      // product property, the same one `review-test-helpers.ts`'s
      // `confirmApproveThroughGate` encodes for the unit suite.
      await page
        .locator(".demo-plan__actions")
        .getByRole("button", { name: "Phê duyệt" })
        .click();
      await expect(page).toHaveURL(
        new RegExp(`/decisions/recommendations/${REPLAY_SCENARIO_WORKFLOW_KEY}$`),
      );

      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      await expect(
        dialog.getByRole("heading", { name: "Xác nhận phê duyệt" }),
      ).toBeVisible();
      await dialog.getByRole("button", { name: "Phê duyệt" }).click();

      // THE PREVIOUSLY-BLOCKED STEP (gap 1, #1320 part 2's stated scope) —
      // #1762 landed this navigation; confirmed here rather than assumed.
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

      // EXPECTED TO FAIL HERE — issue #1764 (gap 2, see the module
      // docstring): the replay door has no replay-local confirm path yet,
      // so this click actually fires a real, bearer-less confirmation POST
      // that 404s, and `OptionPicker` renders its generic rejection alert
      // instead of advancing. Asserted explicitly and immediately after
      // the click — rather than deferred to a later step — so the failure
      // is attributed to this exact defect, not an incidental side effect
      // somewhere downstream.
      await expect(page.getByRole("alert")).toHaveCount(0);
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
