import { buildAnalyticsMetricHref } from "../../analytics/main-kpis";
import { getPlanCaveats } from "../../plan-caveats";
import { buildPlanImpact, type PlanReviewContent } from "../../plan-reviews";

import { recommendationFixtures } from "../../recommendations";
import {
  PREVENT_REFUND_WORKFLOW_KEY,
  buildPreventRefundReviewInputDefaults,
  defaultPreventRefundAnalyticsMetricKey,
} from "./review";

const fixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === PREVENT_REFUND_WORKFLOW_KEY,
);

if (!fixtureEntry) {
  throw new Error("Missing prevent_refund_8c recommendation fixture");
}

const preventRefundFixture = fixtureEntry;

/** "2026-07-19 09:00" the way a seller reads a deadline. */
function formatSellerDeadline(value: string): string {
  const [isoDate, time = ""] = value.split(" ");
  const [year, month, day] = isoDate.split("-");
  return `${time} ngày ${day}/${month}/${year}`.trim();
}

/**
 * The already-calculated refund amount, the way a seller reads money. This is
 * a figure the after-sales system produced — never an estimate Juli invented,
 * and never a projected impact (ADR-055 item 16).
 */
function formatSellerAmount(value: string): string {
  return `${Number(value).toLocaleString("de-DE")} ₫`;
}

/** Seller-language names for the refund types the field data can carry. */
const REFUND_TYPE_LABELS: Record<string, string> = {
  partial: "hoàn tiền một phần",
  full: "hoàn tiền toàn bộ",
};

/** The seller's branch: approve the refund, or reject it. */
const APPROVE_DECISION = "Phê duyệt";

/**
 * Situation → Decision → Details plan review for `prevent_refund_8c` (ADR-055
 * items 1, 8, 13; scope cuts per item 14 — no risks display, no
 * decision-options editing).
 *
 * Seven known fields collapse into a single summary row, the same
 * summarise-don't-enumerate demonstration as `prevent_return_8b`.
 *
 * `seller_decision` is a branch discriminator, so Juli pre-commits to one
 * branch in the proposal and rests the alternative behind the read-only
 * options disclosure; `reject_reason` is gated into `details` on the reject
 * branch alone.
 *
 * The workflow's class-D no-act promise is *not* written here: it is a typed
 * caveat the card rests as a trust line in the Decision section, so the
 * proposal must not repeat it. `risks` is not rendered nor paraphrased.
 */
export function getPreventRefundPlanReview(
  defaults = buildPreventRefundReviewInputDefaults(),
): PlanReviewContent {
  const deadline = formatSellerDeadline(defaults.decision_deadline);
  const amount = formatSellerAmount(defaults.calculated_amount);
  const refundType =
    REFUND_TYPE_LABELS[defaults.refund_type] ?? defaults.refund_type;
  const isApproveBranch = defaults.seller_decision === APPROVE_DECISION;
  const rejectReason = defaults.reject_reason.trim();
  const details =
    !isApproveBranch && rejectReason.length > 0
      ? {
          detailLines: [`Lý do gửi cho người mua: ${rejectReason}.`],
        }
      : undefined;

  return {
    workflowKey: PREVENT_REFUND_WORKFLOW_KEY,
    title: preventRefundFixture.title,
    situation: {
      summary: `Yêu cầu hoàn tiền đơn ${defaults.order_id} · 7 thông tin`,
      disclosureQuestion: "Juli dựa vào thông tin nào?",
      detailLines: [
        `Yêu cầu hậu mãi mang mã ${defaults.aftersale_id} đang chờ quyết định.`,
        `Yêu cầu thuộc đơn hàng ${defaults.order_id}.`,
        `Lý do yêu cầu: ${defaults.request_reason.toLowerCase()}.`,
        `Số tiền đã tính được là ${amount}.`,
        `Đây là ${refundType}.`,
        `Không có trả hàng vật lý kèm theo — việc đó thuộc luồng trả hàng riêng.`,
        `Hạn quyết định là ${deadline}.`,
      ],
      analyticsMetricHref: buildAnalyticsMetricHref(
        defaultPreventRefundAnalyticsMetricKey,
      ),
    },
    // The tied Main KPI is the workflow's existing binding — GMV (ADR-055
    // item 15). No magnitude is projected (item 16); the amount above is the
    // system's own calculation, shown as known context.
    impact: buildPlanImpact(defaultPreventRefundAnalyticsMetricKey),
    decision: {
      proposal: isApproveBranch
        ? `Juli đề xuất phê duyệt hoàn ${amount} cho đơn hàng ${defaults.order_id} trước hạn ${deadline}.`
        : `Juli đề xuất từ chối yêu cầu hoàn tiền đơn ${defaults.order_id} trước hạn ${deadline}.`,
      // The workflow's pre-authored reasoning from the shared fixture table.
      reasoning: preventRefundFixture.reasoning,
      caveats: getPlanCaveats(PREVENT_REFUND_WORKFLOW_KEY),
      recommendedOptions: {
        disclosureQuestion: "Juli cân nhắc những lựa chọn nào?",
        groups: [
          {
            label: "Quyết định cho yêu cầu hoàn tiền",
            options: [
              {
                value: "Phê duyệt yêu cầu hoàn tiền",
                proposed: isApproveBranch,
              },
              {
                value: "Từ chối yêu cầu hoàn tiền",
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
