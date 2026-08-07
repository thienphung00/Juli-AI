import { buildAnalyticsMetricHref } from "../../analytics/main-kpis";
import { getPlanCaveats } from "../../plan-caveats";
import { buildPlanImpact, type PlanReviewContent } from "../../plan-reviews";

import { recommendationFixtures } from "../../recommendations";
import {
  PREVENT_RETURN_WORKFLOW_KEY,
  buildPreventReturnReviewInputDefaults,
  defaultPreventReturnAnalyticsMetricKey,
} from "./review";

const fixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === PREVENT_RETURN_WORKFLOW_KEY,
);

if (!fixtureEntry) {
  throw new Error("Missing prevent_return_8b recommendation fixture");
}

const preventReturnFixture = fixtureEntry;

/** "2026-07-20 12:00" the way a seller reads a deadline. */
function formatSellerDeadline(value: string): string {
  const [isoDate, time = ""] = value.split(" ");
  const [year, month, day] = isoDate.split("-");
  return `${time} ngày ${day}/${month}/${year}`.trim();
}

/** The seller's branch: approve the return, or reject it. */
const APPROVE_DECISION = "Phê duyệt";

/**
 * Situation → Decision → Details plan review for `prevent_return_8b` (ADR-055
 * items 1, 8, 13; scope cuts per item 14 — no risks display, no
 * decision-options editing).
 *
 * The heaviest known-field load in the set: **seven** known fields collapse
 * into a single summary row, which is what the summarise-don't-enumerate
 * pattern exists to prove.
 *
 * `seller_decision` is a branch discriminator, so Juli pre-commits to one
 * branch in the proposal and rests the alternative behind the read-only
 * options disclosure. `reject_reason` is relevant only on the reject branch
 * and is gated into `details` rather than rendered always.
 *
 * Two fields are deliberately not asked for here:
 *
 * - `resellable_quantity` is gone from the approval flow entirely — it is a
 *   post-execution outcome ("sau kiểm tra"), removed at the source in
 *   `review.ts` rather than hidden here (issue #769).
 * - The restock-gating warning lives in `risks`, whose display is deferred
 *   (ADR-055 items 9 and 14). It is neither rendered nor paraphrased into body
 *   copy below; the restock step is described only as a later, separate step.
 *
 * The workflow's class-D no-act promise is *not* written here: it is a typed
 * caveat the card rests as a trust line in the Decision section, so the
 * proposal must not repeat it.
 */
export function getPreventReturnPlanReview(
  defaults = buildPreventReturnReviewInputDefaults(),
): PlanReviewContent {
  const deadline = formatSellerDeadline(defaults.decision_deadline);
  const isApproveBranch = defaults.seller_decision === APPROVE_DECISION;
  const rejectReason = defaults.reject_reason.trim();
  const details =
    !isApproveBranch && rejectReason.length > 0
      ? {
          detailLines: [`Lý do gửi cho người mua: ${rejectReason}.`],
        }
      : undefined;

  return {
    workflowKey: PREVENT_RETURN_WORKFLOW_KEY,
    title: preventReturnFixture.title,
    situation: {
      summary: `Yêu cầu trả hàng đơn ${defaults.order_id} · 7 thông tin`,
      disclosureQuestion: "Juli dựa vào thông tin nào?",
      detailLines: [
        `Người mua đã gửi yêu cầu trả hàng mang mã ${defaults.return_id}.`,
        `Yêu cầu thuộc đơn hàng ${defaults.order_id}.`,
        `Lý do trả hàng: ${defaults.return_reason.toLowerCase()}.`,
        `Hạn quyết định là ${deadline}.`,
        `Tình trạng hiện tại: ${defaults.rma_state.toLowerCase()}.`,
        `Theo quy tắc hiện có, đây là lần trả đầu và chưa có dấu hiệu bất thường.`,
        `Nhập lại kho là một bước riêng ở sau, không nằm trong lần phê duyệt này.`,
      ],
      analyticsMetricHref: buildAnalyticsMetricHref(
        defaultPreventReturnAnalyticsMetricKey,
      ),
    },
    // The tied Main KPI is the workflow's existing binding — GMV (ADR-055
    // item 15). No magnitude is projected (item 16).
    impact: buildPlanImpact(defaultPreventReturnAnalyticsMetricKey),
    decision: {
      proposal: isApproveBranch
        ? `Juli đề xuất phê duyệt yêu cầu trả hàng đơn ${defaults.order_id} trước hạn ${deadline}.`
        : `Juli đề xuất từ chối yêu cầu trả hàng đơn ${defaults.order_id} trước hạn ${deadline}.`,
      // The workflow's pre-authored reasoning from the shared fixture table.
      reasoning: preventReturnFixture.reasoning,
      caveats: getPlanCaveats(PREVENT_RETURN_WORKFLOW_KEY),
      recommendedOptions: {
        disclosureQuestion: "Juli cân nhắc những lựa chọn nào?",
        groups: [
          {
            label: "Quyết định cho yêu cầu trả hàng",
            options: [
              {
                value: "Phê duyệt yêu cầu trả hàng",
                proposed: isApproveBranch,
              },
              {
                value: "Từ chối yêu cầu trả hàng",
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
