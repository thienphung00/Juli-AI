import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DemoStateProvider } from "../demo-state";
import { RecommendationReview } from "../recommendation-review";
import {
  PLAN_COMPARISON_CURRENT_LABEL,
  PLAN_COMPARISON_PROPOSED_LABEL,
} from "../../lib/plan-reviews";
import { getOptimizeProductPlanReview } from "../../lib/workflows/optimize-product";
import { getDeleteActivityPlanReview } from "../../lib/workflows/delete-activity";
import { OPTIMIZE_PRODUCT_WORKFLOW_KEY } from "../../lib/reviews";
import { REPLAY_SCENARIO_RUN_ID } from "../../lib/run-surface/replay-scenario";
import { SELLER_APPROVE_GATE } from "../../lib/review-seller-copy";

/**
 * Issue #1916 — the review page built as a before/after (ElevenLabs /
 * Mistral references): the current listing on one side, the proposal on
 * the other, each explicitly labelled in Vietnamese so a seller never has
 * to infer which column is their live listing. The reason travels with
 * the change (Shopify reference) — visible, never behind hover or a
 * tooltip. The two-step consent gate (ADR-055 item 8 / #1317) is intact.
 */

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
    push,
    refresh: vi.fn(),
    replace: vi.fn(),
  })),
  usePathname: vi.fn(
    () => "/decisions/recommendations/optimize_product_2",
  ),
  useSearchParams: vi.fn(),
}));

function renderOptimizeReview() {
  return render(
    <DemoStateProvider>
      <RecommendationReview workflowKey={OPTIMIZE_PRODUCT_WORKFLOW_KEY} />
    </DemoStateProvider>,
  );
}

describe("Review page before/after comparison (issue #1916)", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    push.mockClear();
  });

  it("labels current and proposed explicitly, in Vietnamese, so the live listing needs no inference", () => {
    const plan = getOptimizeProductPlanReview();
    renderOptimizeReview();

    const comparison = screen.getByTestId("plan-comparison");
    const table = within(comparison).getByRole("table");

    expect(
      within(table).getByRole("columnheader", {
        name: PLAN_COMPARISON_CURRENT_LABEL,
      }),
    ).toBeInTheDocument();
    expect(
      within(table).getByRole("columnheader", {
        name: PLAN_COMPARISON_PROPOSED_LABEL,
      }),
    ).toBeInTheDocument();

    // The labels are explicit Vietnamese about whose listing is whose.
    expect(PLAN_COMPARISON_CURRENT_LABEL).toContain("shop của bạn");

    // Field names in Vietnamese, one row per field of the change.
    expect(plan.comparison).toBeDefined();
    for (const row of plan.comparison?.rows ?? []) {
      const rowHeader = within(table).getByRole("rowheader", {
        name: row.fieldLabel,
      });
      const tableRow = rowHeader.closest("tr") as HTMLElement;
      expect(within(tableRow).getByText(row.current)).toBeInTheDocument();
      expect(within(tableRow).getByText(row.proposed)).toBeInTheDocument();
    }

    // The current side really is the live listing.
    expect(within(table).getByText("Son môi số 12")).toBeInTheDocument();
  });

  it("renders the rationale visibly on the page — no hover, no tooltip, no disclosure click", () => {
    const plan = getOptimizeProductPlanReview();
    renderOptimizeReview();

    const reason = plan.comparison?.reason ?? "";
    expect(reason.trim().length).toBeGreaterThan(0);

    const rendered = screen.getByText(reason);
    expect(rendered).toBeVisible();
    expect(rendered).not.toHaveAttribute("title");
    expect(rendered.closest("[role='tooltip']")).toBeNull();
    // Not inside any collapsed disclosure.
    expect(rendered.closest("[aria-expanded='false']")).toBeNull();
  });

  it("keeps the two-step consent gate: the second Phê duyệt only arms the dialog, and only its confirm authorises", async () => {
    const user = userEvent.setup();
    renderOptimizeReview();

    // Second Phê duyệt (the first lives on the list card) arms the dialog…
    await user.click(screen.getByRole("button", { name: "Phê duyệt" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(SELLER_APPROVE_GATE.description);
    expect(push).not.toHaveBeenCalled();

    // …cancel disarms without authorising anything…
    await user.click(
      within(dialog).getByRole("button", {
        name: SELLER_APPROVE_GATE.cancelLabel,
      }),
    );
    expect(push).not.toHaveBeenCalled();

    // …and only the dialog's own confirm authorises.
    await user.click(screen.getByRole("button", { name: "Phê duyệt" }));
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: SELLER_APPROVE_GATE.confirmLabel,
      }),
    );
    expect(push).toHaveBeenCalledWith(
      `/decisions/in-progress/${REPLAY_SCENARIO_RUN_ID}`,
    );
  });

  it("is additive: a plan without a comparison renders no comparison table", () => {
    expect(getDeleteActivityPlanReview().comparison).toBeUndefined();

    render(
      <DemoStateProvider>
        <RecommendationReview workflowKey="delete_activity_7b" />
      </DemoStateProvider>,
    );

    expect(screen.queryByTestId("plan-comparison")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("Dictionary coverage for the comparison labels (ADR-028)", () => {
  it("keys the current/proposed column labels in dictionary.md", () => {
    const dictionary = readFileSync(
      join(process.cwd(), "..", "..", "dictionary.md"),
      "utf8",
    );

    expect(dictionary).toContain(PLAN_COMPARISON_CURRENT_LABEL);
    expect(dictionary).toContain(PLAN_COMPARISON_PROPOSED_LABEL);
  });
});
