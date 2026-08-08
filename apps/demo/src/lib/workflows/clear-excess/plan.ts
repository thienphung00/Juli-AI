import { buildAnalyticsMetricHref } from "../../analytics/main-kpis";
import { getPlanCaveats } from "../../plan-caveats";
import { buildPlanImpact, type PlanReviewContent } from "../../plan-reviews";

import { recommendationFixtures } from "../../recommendations";
import {
  CLEAR_EXCESS_WORKFLOW_KEY,
  buildClearExcessReviewInputDefaults,
  defaultClearExcessAnalyticsMetricKey,
} from "./review";

const fixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === CLEAR_EXCESS_WORKFLOW_KEY,
);

if (!fixtureEntry) {
  throw new Error("Missing clear_excess_4 recommendation fixture");
}

const clearExcessFixture = fixtureEntry;

/** ISO date from the field data rendered the way a seller reads a date. */
function formatSellerDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-");
  return `${day}/${month}/${year}`;
}

/**
 * Situation → Decision → Details plan review for `clear_excess_4` (ADR-055
 * items 1, 8, 13; scope cuts per item 14 — no risks display, no
 * decision-options editing).
 *
 * Three known fields collapse into one summary row. Of the four seller
 * decisions, the two decision-grade ones — the markdown and the promotion type
 * — rest in the Decision section, and the promotion window is branch-gated
 * execution detail, so `details` is present here.
 *
 * `clear_excess_4` carries the irreversibility warning in `risks`. Its display
 * is deliberately deferred (ADR-055 items 9 and 14): it is neither rendered nor
 * paraphrased into body copy anywhere below.
 */
export function getClearExcessPlanReview(): PlanReviewContent {
  const defaults = buildClearExcessReviewInputDefaults();

  return {
    workflowKey: CLEAR_EXCESS_WORKFLOW_KEY,
    title: clearExcessFixture.title,
    situation: {
      summary: "Lô hàng “Áo khoác gió mùa hè” · 3 thông tin",
      disclosureQuestion: "Juli dựa vào thông tin nào?",
      detailLines: [
        "Juli đang theo dõi lô “Áo khoác gió mùa hè” — 142 đơn vị, đã tồn 68 ngày.",
        "Điều kiện Flash Sale chưa được kiểm tra, nên Juli chưa đưa Flash Sale vào đề xuất này.",
        "Xoá tồn kho sàn về 0 là một bước riêng ở sau, không nằm trong lần phê duyệt này.",
      ],
      analyticsMetricHref: buildAnalyticsMetricHref(
        defaultClearExcessAnalyticsMetricKey,
      ),
    },
    // The tied Main KPI is the workflow's existing `analyticsMetricKey`
    // binding — AOV for clear_excess_4 (ADR-055 item 15). Nothing new is
    // mapped here, and no magnitude is projected (item 16); the fixture's
    // projected VND amount is deliberately left off the card.
    impact: buildPlanImpact(defaultClearExcessAnalyticsMetricKey),
    decision: {
      proposal: `Juli đề xuất giảm ${defaults.markdown_baseline}% giá lô “Áo khoác gió mùa hè” bằng chương trình ${defaults.activity_type.toLowerCase()} để xả hàng tồn nhanh hơn.`,
      // The workflow's pre-authored reasoning from the shared fixture table —
      // revealed behind the question-labelled disclosure, sanitized at render.
      reasoning: clearExcessFixture.reasoning,
      caveats: getPlanCaveats(CLEAR_EXCESS_WORKFLOW_KEY),
    },
    details: {
      detailLines: [
        `Chương trình chạy từ ngày ${formatSellerDate(defaults.promotion_start_date)} đến hết ngày ${formatSellerDate(defaults.promotion_end_date)}.`,
      ],
    },
  };
}
