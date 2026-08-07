import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RecommendationReview } from "../components/recommendation-review";
import { IMPACT_UNAVAILABLE_TEXT } from "../components/impact-block";
import { AnalyticsDataProvider } from "../lib/analytics/analytics-data-context";
import { createMockDemoAnalyticsEnvelope } from "../lib/analytics/__tests__/fixtures";
import {
  IMPACT_METRIC_KEYS,
  buildAnalyticsMetricHref,
  getMainKpiDefinition,
} from "../lib/analytics/main-kpis";
import {
  IMPACT_DIRECTIONAL_GOALS,
  getWorkflowPlanReview,
} from "../lib/plan-reviews";
import { recommendationFixtures } from "../lib/recommendations";
import { REVIEW_UI_BANNED_PATTERNS } from "../lib/review-seller-copy";
import { CREATE_ACTIVITY_WORKFLOW_KEY } from "../lib/workflows/create-activity";
import { getCreateActivityPlanReview } from "../lib/workflows/create-activity/plan";
import { DELETE_ACTIVITY_WORKFLOW_KEY } from "../lib/workflows/delete-activity";
import { getDeleteActivityPlanReview } from "../lib/workflows/delete-activity/plan";
import { OPTIMIZE_PRODUCT_WORKFLOW_KEY } from "../lib/workflows/optimize-product";
import { getOptimizeProductPlanReview } from "../lib/workflows/optimize-product/plan";
import { UPDATE_ACTIVITY_WORKFLOW_KEY } from "../lib/workflows/update-activity";
import { getUpdateActivityPlanReview } from "../lib/workflows/update-activity/plan";
import { confirmApproveThroughGate } from "./review-test-helpers";

/**
 * Impact block — the tied Main KPI's real value, trend and directional goal
 * (ADR-055 items 15–17, issue #771).
 *
 * Every workflow migrated onto the plan-review spine registers here and
 * inherits the whole assertion set, so the four rollout slices (#766–769)
 * only add a row.
 */
interface ImpactTableEntry {
  workflowKey: string;
  getPlan: () => ReturnType<typeof getDeleteActivityPlanReview>;
}

const IMPACT_WORKFLOWS: ImpactTableEntry[] = [
  {
    workflowKey: DELETE_ACTIVITY_WORKFLOW_KEY,
    getPlan: getDeleteActivityPlanReview,
  },
  {
    workflowKey: OPTIMIZE_PRODUCT_WORKFLOW_KEY,
    getPlan: getOptimizeProductPlanReview,
  },
  {
    workflowKey: CREATE_ACTIVITY_WORKFLOW_KEY,
    getPlan: getCreateActivityPlanReview,
  },
  {
    workflowKey: UPDATE_ACTIVITY_WORKFLOW_KEY,
    getPlan: getUpdateActivityPlanReview,
  },
];

/**
 * Real values from the shared envelope fixture, keyed by metric. Nothing here
 * is authored for the impact block — these are the same series the Analytics
 * screen reads.
 */
const EXPECTED_FROM_ENVELOPE: Record<
  string,
  { formattedValue: string; delta: string }
> = {
  ctor: { formattedValue: "3,8%", delta: "▲ 19%" },
  "gmv-tiktok": { formattedValue: "485.000.000 ₫", delta: "▲ 15%" },
  aov: { formattedValue: "500.000 ₫", delta: "▲ 11%" },
  "cancellation-rate": { formattedValue: "1,8%", delta: "▼ 28%" },
};

const push = vi.fn();
const mockStartExecution = vi.fn(
  (workflowKey: string) => `exec-${workflowKey}-1`,
);

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
    push,
    refresh: vi.fn(),
    replace: vi.fn(),
  })),
  usePathname: vi.fn(() => "/decisions/recommendations/impact"),
  useSearchParams: vi.fn(),
}));

vi.mock("../components/demo-state", () => ({
  DemoStateProvider: ({ children }: { children: ReactNode }) => children,
  useDemoState: () => ({
    feedback: null,
    mode: "mock" as const,
    mutableState: {
      rejectedRecommendationIds: [],
      approvedRecommendationIds: [],
      workflowInputs: {},
      workflowReviewDrafts: {},
      executionRecords: {},
      executionProgress: {},
      decisionsView: "recommendations" as const,
      analyticsMetric: "net-revenue",
      analyticsRange: "30d" as const,
      settingsDraft: {},
    },
    recommendationContext: null,
    requestSignIn: vi.fn(),
    resetMockState: vi.fn(),
    setRecommendationContext: vi.fn(),
    startExecution: mockStartExecution,
    updateMutableState: vi.fn(),
  }),
}));

function stubAnalyticsFetch(
  envelope = createMockDemoAnalyticsEnvelope(),
): ReturnType<typeof vi.fn> {
  const fetchStub = vi.fn(
    async () =>
      ({
        ok: true,
        json: async () => envelope,
      }) as Response,
  );
  vi.stubGlobal("fetch", fetchStub);
  return fetchStub;
}

describe.each(IMPACT_WORKFLOWS)(
  "Impact block — $workflowKey",
  ({ workflowKey, getPlan }) => {
    const plan = getPlan();
    const metricKey = plan.impact.metricKey;
    const definition = getMainKpiDefinition(metricKey);
    const expected = EXPECTED_FROM_ENVELOPE[metricKey]!;
    const deepLinkName = `Xem ${definition.name} trên Phân tích`;

    function renderSpine() {
      return render(
        <AnalyticsDataProvider>
          <RecommendationReview workflowKey={workflowKey} />
        </AnalyticsDataProvider>,
      );
    }

    beforeEach(() => {
      push.mockClear();
      mockStartExecution.mockClear();
    });

    afterEach(() => {
      vi.unstubAllGlobals();
    });

    it("reads the tied KPI from the workflow's existing binding, never a new map", () => {
      // The Situation deep link already encodes `analyticsMetricKey`; the
      // impact block must resolve to the same metric.
      expect(plan.situation.analyticsMetricHref).toBe(
        buildAnalyticsMetricHref(metricKey),
      );
    });

    it("renders the tied KPI's real current value and trend from the serving envelope", async () => {
      stubAnalyticsFetch();

      renderSpine();

      const impact = screen.getByTestId("plan-impact");
      expect(
        await within(impact).findByText(expected.formattedValue),
      ).toBeInTheDocument();
      expect(within(impact).getByText(expected.delta)).toBeInTheDocument();
      expect(within(impact).getByText(definition.name)).toBeInTheDocument();
    });

    it("shows a directional goal in seller language with no magnitude", async () => {
      stubAnalyticsFetch();

      renderSpine();

      const impact = screen.getByTestId("plan-impact");
      expect(
        within(impact).getByText(plan.impact.directionalGoal),
      ).toBeInTheDocument();
      expect(plan.impact.directionalGoal).toBe(
        IMPACT_DIRECTIONAL_GOALS[metricKey],
      );
      // Directional — carries a direction word, never a number.
      expect(plan.impact.directionalGoal).toMatch(/tăng|giảm/);
      expect(plan.impact.directionalGoal).not.toMatch(/\d/);
    });

    it("is placed prominently — above the decision proposal, not below it", () => {
      stubAnalyticsFetch();

      renderSpine();

      const card = screen.getByTestId("plan-review-card");
      const impact = within(card).getByTestId("plan-impact");
      const decision = within(card).getByTestId("plan-decision");
      expect(
        impact.compareDocumentPosition(decision) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    });

    it("deep links to the tied KPI in Analytics", () => {
      stubAnalyticsFetch();

      renderSpine();

      const impact = screen.getByTestId("plan-impact");
      expect(
        within(impact).getByRole("link", { name: deepLinkName }),
      ).toHaveAttribute("href", buildAnalyticsMetricHref(metricKey));
    });

    it("renders no projected magnitude", async () => {
      stubAnalyticsFetch();

      renderSpine();

      const impact = screen.getByTestId("plan-impact");
      await within(impact).findByText(expected.formattedValue);

      const fixture = recommendationFixtures.find(
        (entry) => entry.workflowKey === workflowKey,
      );
      expect(fixture).toBeDefined();
      if (fixture && fixture.expectedImpactLabel !== "—") {
        expect(impact.textContent ?? "").not.toContain(
          fixture.expectedImpactLabel,
        );
      }
      expect(impact.textContent ?? "").not.toMatch(/dự kiến|ước tính/i);
    });

    it("is byte-identical before and after approval — exactly one state", async () => {
      stubAnalyticsFetch();
      const user = userEvent.setup();

      renderSpine();

      const impact = screen.getByTestId("plan-impact");
      await within(impact).findByText(expected.formattedValue);
      const restingHtml = impact.outerHTML;

      await confirmApproveThroughGate(user);
      expect(mockStartExecution).toHaveBeenCalledTimes(1);

      expect(screen.getByTestId("plan-impact").outerHTML).toBe(restingHtml);
    });

    it("renders an honest unavailable state when the envelope has no value for the metric", async () => {
      const fetchStub = stubAnalyticsFetch(
        createMockDemoAnalyticsEnvelope({
          kpis: {
            [metricKey === "gmv-tiktok" ? "gmv_tiktok" : metricKey]: {
              availability: "unavailable",
              label: definition.name,
            },
          },
        }),
      );

      renderSpine();

      await waitFor(() => expect(fetchStub).toHaveBeenCalled());

      const impact = screen.getByTestId("plan-impact");
      expect(
        await within(impact).findByText(IMPACT_UNAVAILABLE_TEXT),
      ).toBeInTheDocument();
      // Never a placeholder number: the block carries no digits at all when
      // the metric value is missing.
      expect(impact.textContent ?? "").not.toMatch(/\d/);
      // The goal and the Analytics deep link remain — authored, not data.
      expect(
        within(impact).getByText(plan.impact.directionalGoal),
      ).toBeInTheDocument();
      expect(
        within(impact).getByRole("link", { name: deepLinkName }),
      ).toBeInTheDocument();
    });

    it("keeps the impact block free of system vocabulary", async () => {
      stubAnalyticsFetch();

      renderSpine();

      const impact = screen.getByTestId("plan-impact");
      await within(impact).findByText(expected.formattedValue);

      for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
        expect(impact.textContent ?? "").not.toMatch(pattern);
      }
    });
  },
);

describe("Impact block — structural guards across every workflow", () => {
  it("gives every registered plan review an impact block with a digit-free goal", () => {
    let checked = 0;

    for (const fixture of recommendationFixtures) {
      const plan = getWorkflowPlanReview(fixture.workflowKey);
      if (!plan) {
        continue;
      }
      checked += 1;

      expect(plan.impact.metricKey).toBeTruthy();
      expect(plan.impact.directionalGoal).not.toMatch(/\d/);
      if (fixture.expectedImpactLabel !== "—") {
        expect(plan.impact.directionalGoal).not.toContain(
          fixture.expectedImpactLabel,
        );
      }
    }

    expect(checked).toBe(IMPACT_WORKFLOWS.length);
  });

  it("keeps LIVE hours unmapped from any impact goal", () => {
    expect([...IMPACT_METRIC_KEYS].sort()).toEqual(
      ["aov", "cancellation-rate", "ctor", "gmv-tiktok"].sort(),
    );
    expect(Object.keys(IMPACT_DIRECTIONAL_GOALS).sort()).toEqual(
      ["aov", "cancellation-rate", "ctor", "gmv-tiktok"].sort(),
    );
    expect(Object.keys(IMPACT_DIRECTIONAL_GOALS)).not.toContain("live-hours");
  });

  it("authors a directional goal for every tie-able KPI, none with a magnitude", () => {
    for (const metricKey of IMPACT_METRIC_KEYS) {
      const goal = IMPACT_DIRECTIONAL_GOALS[metricKey];
      expect(goal).toMatch(/tăng|giảm/);
      expect(goal).not.toMatch(/\d/);
      for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
        expect(goal).not.toMatch(pattern);
      }
    }
  });
});
