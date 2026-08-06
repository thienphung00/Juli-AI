import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ExecutionRecord } from "@juli/contracts";

import {
  DEFAULT_MUTABLE_MOCK_STATE,
  DEMO_MUTABLE_STATE_STORAGE_KEY,
  DemoStateProvider,
} from "../components/demo-state";
import { InProgressDetailView } from "../app/decisions/in-progress/[executionId]/page";
import {
  InProgressPanel,
  NEEDS_INPUT_FALLBACK_RECOVERY_TEXT,
  getLifecycleStatus,
  getRecoveryText,
  getStepFraction,
} from "../components/in-progress-panel";
import {
  createHeroProductTimeline,
  resetExecutionCountersForTests,
} from "../lib/executions";
import { CREATE_HERO_PRODUCT_WORKFLOW_KEY } from "../lib/reviews";
import { REVIEW_UI_BANNED_PATTERNS } from "../lib/review-seller-copy";

vi.mock("next/navigation", () => ({
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => "/decisions"),
  useParams: vi.fn(() => ({ executionId: "unused" })),
  useRouter: vi.fn(() => ({
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
    push: vi.fn(),
    refresh: vi.fn(),
    replace: vi.fn(),
  })),
}));

function buildExecutionRecord(
  overrides: Partial<ExecutionRecord> & Pick<ExecutionRecord, "executionId">,
): ExecutionRecord {
  const timeline = overrides.timeline ?? createHeroProductTimeline();
  return {
    workflowKey: CREATE_HERO_PRODUCT_WORKFLOW_KEY,
    toolName: "listing.create_hero_product",
    lifecycleStatus: "executing",
    startedAt: "2026-07-16T04:12:00.000Z",
    updatedAt: "2026-07-16T04:12:00.000Z",
    approvedInputs: {
      category_id: "700648",
      brand_id: "BR-1024",
    },
    ...overrides,
    timeline,
  };
}

/**
 * Timeline stopped at step 3 (eligibility-outcome): steps 1–2 succeeded,
 * step 3 failed. The lifecycle derivation resolves this to needs_input;
 * step 3 carries authored recoveryText.
 */
function buildStoppedTimeline() {
  return createHeroProductTimeline().map((step) => {
    if (step.stepNumber <= 2) {
      return { ...step, status: "succeeded" as const };
    }
    if (step.id === "eligibility-outcome") {
      return { ...step, status: "failed" as const };
    }
    return step;
  });
}

function buildExecutingTimeline() {
  return createHeroProductTimeline().map((step, index) =>
    index === 0 ? { ...step, status: "running" as const } : step,
  );
}

function seedMutableState(records: ExecutionRecord[]) {
  localStorage.setItem(
    DEMO_MUTABLE_STATE_STORAGE_KEY,
    JSON.stringify({
      ...DEFAULT_MUTABLE_MOCK_STATE,
      decisionsView: "in-progress",
      executionRecords: Object.fromEntries(
        records.map((record) => [record.executionId, record]),
      ),
      executionProgress: Object.fromEntries(
        records.map((record) => [record.executionId, record.lifecycleStatus]),
      ),
    }),
  );
}

function renderInProgressPanel() {
  return render(
    <DemoStateProvider>
      <InProgressPanel panelId="in-progress-panel" />
    </DemoStateProvider>,
  );
}

function renderInProgressDetail(executionId: string) {
  return render(
    <DemoStateProvider>
      <InProgressDetailView executionId={executionId} />
    </DemoStateProvider>,
  );
}

describe("needs_input surfacing (DPR-14, issue #773)", () => {
  beforeEach(() => {
    localStorage.clear();
    resetExecutionCountersForTests();
  });

  it("shows the lifecycle label and the active step's recoveryText on a needs_input card without expanding", async () => {
    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-needs-input-recovery-1",
        lifecycleStatus: "needs_input",
        timeline: buildStoppedTimeline(),
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      expect(screen.getByText("Cần thêm thông tin")).toBeInTheDocument();
    });

    // The authored recovery text of the stopped step is visible collapsed.
    expect(
      screen.getByText(
        "Quay lại bước lấy danh mục hoặc bổ sung điều kiện còn thiếu trước khi tiếp tục.",
      ),
    ).toBeInTheDocument();
  });

  it("routes the recovery text through the seller-copy sanitizer", async () => {
    const timeline = createHeroProductTimeline().map((step) =>
      step.id === "eligibility-outcome"
        ? {
            ...step,
            status: "failed" as const,
            recoveryText:
              "Bổ sung SKU FBS còn thiếu trong `inventory.check` trước khi tiếp tục.",
          }
        : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-needs-input-sanitized-1",
        lifecycleStatus: "needs_input",
        timeline,
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      expect(screen.getByText("Cần thêm thông tin")).toBeInTheDocument();
    });

    const card = screen.getByRole("article");
    const cardText = card.textContent ?? "";

    // Internal vocabulary is rewritten into seller language.
    expect(cardText).toContain("SKU trên kho giao hàng");

    // Nothing on the card trips the banned-pattern guard.
    for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
      expect(
        cardText.match(pattern),
        `Banned pattern found on needs_input card: ${pattern}`,
      ).toBeNull();
    }
  });

  it("falls back to authored generic recovery copy when the stopped step has no recoveryText", async () => {
    // Fail step 1 (get-category), which carries no recoveryText.
    const timeline = createHeroProductTimeline().map((step, index) =>
      index === 0 ? { ...step, status: "failed" as const } : step,
    );

    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-needs-input-fallback-1",
        lifecycleStatus: "needs_input",
        timeline,
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      expect(
        screen.getByText(NEEDS_INPUT_FALLBACK_RECOVERY_TEXT),
      ).toBeInTheDocument();
    });
  });

  it("keeps needs_input visually distinct from executing and exposes the lifecycle status on both cards", async () => {
    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-distinct-executing-1",
        lifecycleStatus: "executing",
        timeline: buildExecutingTimeline(),
      }),
      buildExecutionRecord({
        executionId: "exec-distinct-needs-input-1",
        lifecycleStatus: "needs_input",
        timeline: buildStoppedTimeline(),
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      expect(screen.getAllByRole("article")).toHaveLength(2);
    });

    const articles = screen.getAllByRole("article");
    const executingCard = articles.find(
      (article) =>
        article.getAttribute("data-lifecycle-status") === "executing",
    );
    const needsInputCard = articles.find(
      (article) =>
        article.getAttribute("data-lifecycle-status") === "needs_input",
    );

    // Lifecycle status is exposed for downstream consumers to gate on.
    expect(executingCard).toBeDefined();
    expect(needsInputCard).toBeDefined();
    expect(executingCard).not.toBe(needsInputCard);

    // The stopped card carries a distinct visual treatment; the running one does not.
    expect(needsInputCard!.className).toContain("execution-card--needs-input");
    expect(executingCard!.className).not.toContain(
      "execution-card--needs-input",
    );

    // The recovery block only exists on the stopped card.
    expect(
      needsInputCard!.querySelector(".execution-card__recovery"),
    ).not.toBeNull();
    expect(
      executingCard!.querySelector(".execution-card__recovery"),
    ).toBeNull();
  });

  it("introduces no failed/error/thất bại framing on the collapsed needs_input card", async () => {
    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-no-failure-framing-1",
        lifecycleStatus: "needs_input",
        timeline: buildStoppedTimeline(),
      }),
    ]);

    renderInProgressPanel();

    await waitFor(() => {
      expect(screen.getByText("Cần thêm thông tin")).toBeInTheDocument();
    });

    const cardText = screen.getByRole("article").textContent ?? "";
    expect(cardText).not.toMatch(/thất bại/i);
    expect(cardText).not.toMatch(/\bfailed\b/i);
    expect(cardText).not.toMatch(/\berror\b/i);
  });

  it("keeps the step fraction at the stopped step and does not advance it", async () => {
    const record = buildExecutionRecord({
      executionId: "exec-frozen-fraction-1",
      lifecycleStatus: "needs_input",
      timeline: buildStoppedTimeline(),
    });

    // Pure derivation: fraction is pinned to the stopped step (step 3 of 14).
    expect(getStepFraction(record)).toBe("3 / 14");

    seedMutableState([record]);

    renderInProgressPanel();

    await waitFor(() => {
      expect(screen.getByText("Bước 3 / 14")).toBeInTheDocument();
    });

    expect(screen.queryByText("Bước 4 / 14")).not.toBeInTheDocument();
  });

  it("exposes the lifecycle status through getLifecycleStatus for downstream gating", () => {
    const stopped = buildExecutionRecord({
      executionId: "exec-gate-1",
      lifecycleStatus: "needs_input",
      timeline: buildStoppedTimeline(),
    });
    const running = buildExecutionRecord({
      executionId: "exec-gate-2",
      lifecycleStatus: "executing",
      timeline: buildExecutingTimeline(),
    });

    expect(getLifecycleStatus(stopped)).toBe("needs_input");
    expect(getLifecycleStatus(running)).toBe("executing");
    expect(getLifecycleStatus(stopped)).not.toBe(getLifecycleStatus(running));
  });

  it("returns recovery text only for needs_input records", () => {
    const stopped = buildExecutionRecord({
      executionId: "exec-recovery-only-1",
      lifecycleStatus: "needs_input",
      timeline: buildStoppedTimeline(),
    });
    const running = buildExecutionRecord({
      executionId: "exec-recovery-only-2",
      lifecycleStatus: "executing",
      timeline: buildExecutingTimeline(),
    });

    expect(getRecoveryText(stopped)).toBe(
      "Quay lại bước lấy danh mục hoặc bổ sung điều kiện còn thiếu trước khi tiếp tục.",
    );
    expect(getRecoveryText(running)).toBeUndefined();
  });

  it("shows the recovery text on the needs_input detail view with the lifecycle status exposed", async () => {
    seedMutableState([
      buildExecutionRecord({
        executionId: "exec-detail-needs-input-1",
        lifecycleStatus: "needs_input",
        timeline: buildStoppedTimeline(),
      }),
    ]);

    renderInProgressDetail("exec-detail-needs-input-1");

    await waitFor(() => {
      expect(screen.getByText("Cần thêm thông tin")).toBeInTheDocument();
    });

    const cards = screen.getAllByRole("article");
    const needsInputCard = cards.find(
      (card) => card.getAttribute("data-lifecycle-status") === "needs_input",
    );
    expect(needsInputCard).toBeDefined();

    expect(
      within(needsInputCard!).getByText(
        "Quay lại bước lấy danh mục hoặc bổ sung điều kiện còn thiếu trước khi tiếp tục.",
      ),
    ).toBeInTheDocument();

    // Step fraction on the detail view is pinned to the stopped step too.
    expect(screen.getByText("Bước 3 / 14")).toBeInTheDocument();
  });
});
