import { buildAnalyticsMetricHref } from "../../analytics/main-kpis";
import { getPlanCaveats } from "../../plan-caveats";
import { buildPlanImpact, type PlanReviewContent } from "../../plan-reviews";

import { recommendationFixtures } from "../../recommendations";
import {
  PREVENT_CANCELLATION_WORKFLOW_KEY,
  buildPreventCancellationReviewInputDefaults,
  defaultPreventCancellationAnalyticsMetricKey,
} from "./review";

const fixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === PREVENT_CANCELLATION_WORKFLOW_KEY,
);

if (!fixtureEntry) {
  throw new Error("Missing prevent_cancellation_8a recommendation fixture");
}

const preventCancellationFixture = fixtureEntry;

/** "2026-07-18 17:00" the way a seller reads a deadline. */
function formatSellerDeadline(value: string): string {
  const [isoDate, time = ""] = value.split(" ");
  const [year, month, day] = isoDate.split("-");
  return `${time} ngày ${day}/${month}/${year}`.trim();
}

/** The seller's branch: approve the cancellation, or reject it. */
const APPROVE_DECISION = "Phê duyệt";

/**
 * Situation → Decision → Details plan review for `prevent_cancellation_8a`
 * (ADR-055 items 1, 8, 13; scope cuts per item 14 — no risks display, no
 * decision-options editing).
 *
 * Five known fields collapse into one summary row. `seller_decision` is a
 * branch discriminator, so Juli pre-commits to one branch in the proposal and
 * rests the alternative behind the read-only options disclosure;
 * `reject_reason` belongs to the reject branch alone and is gated into
 * `details` rather than rendered always.
 *
 * The workflow's class-D no-act promise is *not* written here: it is a typed
 * caveat that the card rests as a trust line in the Decision section, so the
 * proposal must not say the same thing a second time.
 *
 * `prevent_cancellation_8a` carries a stock-hold warning in `risks`. Its
 * display is deliberately deferred (ADR-055 items 9 and 14): it is neither
 * rendered nor paraphrased into body copy below.
 */
export function getPreventCancellationPlanReview(
  defaults = buildPreventCancellationReviewInputDefaults(),
): PlanReviewContent {
  const deadline = formatSellerDeadline(defaults.decision_deadline);
  const isApproveBranch = defaults.seller_decision === APPROVE_DECISION;
  // Only the chosen branch renders. On approve there is no branch-gated
  // detail at all, so the Details section is absent rather than an empty stub.
  const rejectReason = defaults.reject_reason.trim();
  const details =
    !isApproveBranch && rejectReason.length > 0
      ? {
          detailLines: [`Lý do gửi cho người mua: ${rejectReason}.`],
        }
      : undefined;

  return {
    workflowKey: PREVENT_CANCELLATION_WORKFLOW_KEY,
    title: preventCancellationFixture.title,
    situation: {
      summary: `Yêu cầu huỷ đơn ${defaults.order_id} · 5 thông tin`,
      disclosureQuestion: "Juli dựa vào thông tin nào?",
      detailLines: [
        `Người mua đã gửi yêu cầu huỷ mang mã ${defaults.cancel_id}.`,
        `Yêu cầu thuộc đơn hàng ${defaults.order_id}.`,
        `Lý do người mua nêu: ${defaults.buyer_reason.toLowerCase()}.`,
        `Hạn quyết định là ${deadline}.`,
        `${defaults.eligibility}.`,
      ],
      analyticsMetricHref: buildAnalyticsMetricHref(
        defaultPreventCancellationAnalyticsMetricKey,
      ),
    },
    // The tied Main KPI is the workflow's existing binding — GMV (ADR-055
    // item 15). No magnitude is projected (item 16).
    impact: buildPlanImpact(defaultPreventCancellationAnalyticsMetricKey),
    decision: {
      proposal: isApproveBranch
        ? `Juli đề xuất phê duyệt yêu cầu huỷ đơn ${defaults.order_id} trước hạn ${deadline}.`
        : `Juli đề xuất từ chối yêu cầu huỷ đơn ${defaults.order_id} trước hạn ${deadline}.`,
      // The workflow's pre-authored reasoning from the shared fixture table.
      reasoning: preventCancellationFixture.reasoning,
      caveats: getPlanCaveats(PREVENT_CANCELLATION_WORKFLOW_KEY),
      recommendedOptions: {
        disclosureQuestion: "Juli cân nhắc những lựa chọn nào?",
        groups: [
          {
            label: "Quyết định cho yêu cầu huỷ",
            options: [
              {
                value: "Phê duyệt yêu cầu huỷ",
                proposed: isApproveBranch,
              },
              {
                value: "Từ chối yêu cầu huỷ",
                proposed: !isApproveBranch,
              },
            ],
          },
        ],
      },
    },
    details,
  };
}
