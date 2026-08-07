import { buildAnalyticsMetricHref } from "../../analytics/main-kpis";
import {
  buildPlanImpact,
  type PlanDecisionOptionGroup,
  type PlanDetailsContent,
  type PlanReviewContent,
} from "../../plan-reviews";

import { recommendationFixtures } from "../../recommendations";
import {
  PROCESS_ORDER_WORKFLOW_KEY,
  defaultProcessOrderAnalyticsMetricKey,
} from "./review";

const fixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === PROCESS_ORDER_WORKFLOW_KEY,
);

if (!fixtureEntry) {
  throw new Error("Missing process_order_5 recommendation fixture");
}

const processOrderFixture = fixtureEntry;

/**
 * The branch discriminator (ADR-055 item 8; the old `shipping_type` field).
 *
 * The two delivery routes are mutually exclusive by contract, and each one
 * makes a different pair of execution fields relevant: TikTok pickup needs the
 * document type and the pickup window; seller delivery needs the tracking
 * number and the carrier. The five-stage form rendered all four regardless.
 *
 * These are internal keys, never seller-facing strings — the rendered labels
 * live in `DELIVERY_OPTION_LABELS` below.
 */
export const PROCESS_ORDER_BRANCH_TIKTOK = "tiktok-pickup";
export const PROCESS_ORDER_BRANCH_SELLER = "seller-delivery";

export const PROCESS_ORDER_BRANCHES = [
  PROCESS_ORDER_BRANCH_TIKTOK,
  PROCESS_ORDER_BRANCH_SELLER,
] as const;

export type ProcessOrderBranch = (typeof PROCESS_ORDER_BRANCHES)[number];

/** The branch Juli pre-commits to, per ADR-055 item 2 — never a blank. */
export const PROCESS_ORDER_RECOMMENDED_BRANCH: ProcessOrderBranch =
  PROCESS_ORDER_BRANCH_TIKTOK;

const DELIVERY_OPTION_LABELS: Record<ProcessOrderBranch, string> = {
  [PROCESS_ORDER_BRANCH_TIKTOK]: "TikTok tới lấy hàng và giao",
  [PROCESS_ORDER_BRANCH_SELLER]: "Shop tự sắp xếp giao hàng",
};

const PROPOSALS: Record<ProcessOrderBranch, string> = {
  [PROCESS_ORDER_BRANCH_TIKTOK]:
    "Juli đề xuất xử lý 6 đơn theo thứ tự ưu tiên và để TikTok tới lấy hàng ngay hôm nay.",
  [PROCESS_ORDER_BRANCH_SELLER]:
    "Juli đề xuất xử lý 6 đơn theo thứ tự ưu tiên và để shop tự sắp xếp giao hàng ngay hôm nay.",
};

/**
 * Branch-gated execution detail. Each branch owns its own two lines and shares
 * none with the other, so switching the discriminator replaces the Details
 * section outright — an abandoned branch's values cannot leak into what would
 * execute (issue #767; PRD #758 user story 12).
 */
const BRANCH_DETAILS: Record<ProcessOrderBranch, PlanDetailsContent> = {
  [PROCESS_ORDER_BRANCH_TIKTOK]: {
    detailLines: [
      "Juli chuẩn bị Hóa đơn thương mại đi kèm cho từng đơn theo yêu cầu của TikTok.",
      "TikTok tới lấy hàng trong khung 09:00 - 12:00 hôm nay.",
    ],
  },
  [PROCESS_ORDER_BRANCH_SELLER]: {
    detailLines: [
      "Juli dùng mã vận đơn TK-20260807-001 mà shop đã cung cấp cho lô đơn này.",
      "Đơn vị vận chuyển SP-TKT-01 sẽ nhận hàng tại kho của shop.",
    ],
  },
};

/**
 * The two decision-grade fields, in traversal order — the processing order and
 * the branch discriminator. ADR-055 item 8 accepts 1–2 items here, so both fit
 * the shared option-group shape and no bespoke layout is introduced.
 */
function buildRecommendedOptionGroups(
  branch: ProcessOrderBranch,
): PlanDecisionOptionGroup[] {
  return [
    {
      label: "Thứ tự xử lý đơn hàng",
      options: [
        { value: "Ưu tiên đơn sắp tới hạn trước", proposed: true },
        { value: "Xử lý theo thứ tự khách đặt hàng" },
      ],
    },
    {
      label: "Hình thức giao hàng",
      options: PROCESS_ORDER_BRANCHES.map((candidate) => ({
        value: DELIVERY_OPTION_LABELS[candidate],
        proposed: candidate === branch || undefined,
      })),
    },
  ];
}

/**
 * Situation → Decision → Details plan review for `process_order_5` (ADR-055
 * items 1, 8, 13; scope cuts per item 14 — no risks display, no
 * decision-options editing).
 *
 * This is the first workflow to populate `details`, because it is the first
 * with a branch discriminator. The plan is a **pure function of the chosen
 * branch**: Details, the proposal sentence and the proposed delivery option
 * are all derived from it, so only the chosen branch's fields can ever reach
 * the screen. The seller-facing switch interaction is the decision-options
 * editing cut by ADR-055 item 14; until it lands the card renders the branch
 * Juli pre-commits to.
 *
 * Three order-context fields Juli already holds collapse into one Situation
 * summary row, and the Analytics deep link resolves to the tied cancellation
 * rate from inside that expansion — there is no separate analytics stage.
 */
export function getProcessOrderPlanReview(
  branch: ProcessOrderBranch = PROCESS_ORDER_RECOMMENDED_BRANCH,
): PlanReviewContent {
  return {
    workflowKey: PROCESS_ORDER_WORKFLOW_KEY,
    title: processOrderFixture.title,
    situation: {
      summary: "6 đơn hàng sắp tới hạn giao · 3 thông tin",
      disclosureQuestion: "Juli dựa vào thông tin nào?",
      detailLines: [
        "Juli đang theo dõi 6 đơn hàng đã thanh toán và đang chờ đưa đi giao.",
        "Cả 6 đơn đều sắp tới hạn giao theo cam kết với khách.",
        "Hình thức giao hàng của từng đơn được đọc trực tiếp từ đơn hàng đã xác thực.",
      ],
      analyticsMetricHref: buildAnalyticsMetricHref(
        defaultProcessOrderAnalyticsMetricKey,
      ),
    },
    // The tied Main KPI is the workflow's existing `analyticsMetricKey`
    // binding — cancellation rate for process_order_5 (ADR-055 item 15).
    // Nothing new is mapped here, and no magnitude is projected (item 16).
    impact: buildPlanImpact(defaultProcessOrderAnalyticsMetricKey),
    decision: {
      proposal: PROPOSALS[branch],
      // The workflow's pre-authored reasoning from the shared fixture table —
      // revealed behind the question-labelled disclosure, sanitized at render.
      reasoning: processOrderFixture.reasoning,
      recommendedOptions: {
        disclosureQuestion: "Juli đã cân nhắc phương án nào?",
        groups: buildRecommendedOptionGroups(branch),
      },
    },
    details: BRANCH_DETAILS[branch],
  };
}
