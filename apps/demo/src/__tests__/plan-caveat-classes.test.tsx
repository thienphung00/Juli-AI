import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlanReviewCard } from "../components/plan-review-card";
import {
  PLAN_REASONING_DISCLOSURE_QUESTION,
  buildPlanImpact,
  type PlanReviewContent,
} from "../lib/plan-reviews";
import type { PlanCaveat } from "../lib/plan-caveats";

/**
 * Per-class presentation rules on the card (ADR-055 item 10; PRD #758 stories
 * 42–44). The two migrated workflows do not between them carry all four
 * classes, so the rules are proved here against a plan holding one caveat of
 * each — the card must apply the rule from the class, never from the string.
 */
const THRESHOLD_TEXT =
  "Ngưỡng chính xác để tạo đề xuất này chưa được xác định — Juli không tự suy diễn con số này.";
const FULFILMENT_TEXT =
  "Luồng giao hàng do TikTok quản lý cho luồng này chưa được hỗ trợ.";
const FEATURE_TEXT =
  "Juli chưa tìm được chương trình khuyến mãi hiện có theo từ khoá.";
const REASSURANCE_TEXT =
  "Juli không tự xử lý thay bạn — bạn là người quyết định.";

const ALL_CLASSES: PlanCaveat[] = [
  { caveatClass: "threshold-undefined", text: THRESHOLD_TEXT },
  { caveatClass: "fulfilment-unsupported", text: FULFILMENT_TEXT },
  { caveatClass: "feature-unavailable", text: FEATURE_TEXT },
  { caveatClass: "reassurance", text: REASSURANCE_TEXT },
];

function buildPlan(caveats: PlanCaveat[]): PlanReviewContent {
  return {
    workflowKey: "caveat_classes_fixture",
    title: "Đề xuất mẫu",
    situation: {
      summary: "Chương trình mẫu · 1 thông tin",
      disclosureQuestion: "Juli dựa vào thông tin nào?",
      detailLines: ["Juli đang theo dõi một chương trình mẫu."],
      analyticsMetricHref: "/analytics/ctor",
    },
    impact: buildPlanImpact("ctor"),
    decision: {
      proposal: "Juli đề xuất kết thúc chương trình mẫu.",
      reasoning: "Chương trình đã hết hiệu lực từ tuần trước.",
      caveats,
    },
  };
}

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
  usePathname: vi.fn(() => "/decisions/recommendations/caveats"),
  useSearchParams: vi.fn(),
}));

vi.mock("../components/demo-state", () => ({
  DemoStateProvider: ({ children }: { children: ReactNode }) => children,
  useDemoState: () => ({
    startExecution: vi.fn(() => "exec-caveats-1"),
  }),
}));

function getReasoningRow() {
  return screen.getByRole("button", {
    name: new RegExp(PLAN_REASONING_DISCLOSURE_QUESTION.replace("?", "\\?")),
  });
}

describe("caveat classes on the plan review card", () => {
  beforeEach(() => {
    push.mockClear();
  });

  it("renders the hidden classes nowhere — resting or fully expanded", async () => {
    const user = userEvent.setup();

    render(<PlanReviewCard plan={buildPlan(ALL_CLASSES)} />);

    const card = screen.getByTestId("plan-review-card");
    expect(card.textContent ?? "").not.toContain(THRESHOLD_TEXT);
    expect(card.textContent ?? "").not.toContain(FULFILMENT_TEXT);

    await user.click(getReasoningRow());
    await user.click(
      screen.getByRole("button", { name: /Juli dựa vào thông tin nào\?/ }),
    );

    expect(card.textContent ?? "").not.toContain(THRESHOLD_TEXT);
    expect(card.textContent ?? "").not.toContain(FULFILMENT_TEXT);
  });

  it("shows a real functional gap only when the seller asks why", async () => {
    const user = userEvent.setup();

    render(<PlanReviewCard plan={buildPlan(ALL_CLASSES)} />);

    // At rest the gap is not on the card — it is an answer, not a warning.
    expect(screen.queryByText(FEATURE_TEXT)).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("plan-reasoning-caveats"),
    ).not.toBeInTheDocument();

    await user.click(getReasoningRow());

    const reasoning = screen.getByTestId("plan-reasoning");
    expect(within(reasoning).getByText(FEATURE_TEXT)).toBeInTheDocument();
    // It sits alongside the reasoning, never in place of it.
    expect(reasoning).toHaveTextContent(
      "Chương trình đã hết hiệu lực từ tuần trước.",
    );

    await user.click(getReasoningRow());
    expect(screen.queryByText(FEATURE_TEXT)).not.toBeInTheDocument();
  });

  it("presents the no-act promise as a resting trust line in the Decision section", () => {
    render(<PlanReviewCard plan={buildPlan(ALL_CLASSES)} />);

    const decision = screen.getByTestId("plan-decision");
    const trustLines = within(decision).getByTestId("plan-trust-lines");

    expect(within(trustLines).getByText(REASSURANCE_TEXT)).toBeInTheDocument();
    // Reassurance, not a limitation: no limits heading anywhere on the card.
    const card = screen.getByTestId("plan-review-card");
    expect(card.textContent ?? "").not.toMatch(/Hạn chế|Giới hạn|Lưu ý/);
    // It rests visible — the seller does not have to expand to be reassured.
    expect(
      within(decision).getByText(
        "Juli đề xuất kết thúc chương trình mẫu.",
      ),
    ).toBeInTheDocument();
  });

  it("renders no trust-line block when the workflow carries no reassurance", () => {
    render(
      <PlanReviewCard
        plan={buildPlan([
          { caveatClass: "threshold-undefined", text: THRESHOLD_TEXT },
        ])}
      />,
    );

    expect(screen.queryByTestId("plan-trust-lines")).not.toBeInTheDocument();
  });

  it("renders no gap block inside the reasoning expansion when there is no gap", async () => {
    const user = userEvent.setup();

    render(
      <PlanReviewCard
        plan={buildPlan([
          { caveatClass: "fulfilment-unsupported", text: FULFILMENT_TEXT },
        ])}
      />,
    );

    await user.click(getReasoningRow());

    expect(screen.getByTestId("plan-reasoning")).toBeInTheDocument();
    expect(
      screen.queryByTestId("plan-reasoning-caveats"),
    ).not.toBeInTheDocument();
  });

  it("applies the rule from the class, not from the string", async () => {
    const user = userEvent.setup();

    // Same sentence, filed as reassurance instead of as a threshold: the card
    // must move it to the trust line without inspecting a single character.
    render(
      <PlanReviewCard
        plan={buildPlan([
          { caveatClass: "reassurance", text: THRESHOLD_TEXT },
        ])}
      />,
    );

    expect(screen.getByTestId("plan-trust-lines")).toHaveTextContent(
      THRESHOLD_TEXT,
    );

    await user.click(getReasoningRow());
    expect(
      screen.queryByTestId("plan-reasoning-caveats"),
    ).not.toBeInTheDocument();
  });
});
