import { buildAnalyticsMetricHref } from "../../analytics/main-kpis";
import {
  buildPlanImpact,
  type PlanNeedsYouUploadField,
  type PlanReviewContent,
} from "../../plan-reviews";

import { getPlanCaveats } from "../../plan-caveats";
import {
  CREATE_HERO_PRODUCT_WORKFLOW_KEY,
  createHeroProductFixture,
  defaultCreateHeroProductAnalyticsMetricKey,
  getCreateHeroProductReviewStages,
} from "./review";

/**
 * The upload descriptors come straight from the field data — the same
 * `kind: "upload"` descriptors the five-stage review carried — so the
 * "needs you" section can never drift from the canonical labels
 * ("Ảnh sản phẩm" required, "Tệp hỗ trợ (nếu danh mục yêu cầu)" optional).
 */
function buildNeedsYouUploadFields(): PlanNeedsYouUploadField[] {
  const inputsStage = getCreateHeroProductReviewStages().find(
    (stage) => stage.stage === "inputs",
  );
  const uploadFields = (inputsStage?.inputFields ?? []).filter(
    (field) => field.kind === "upload",
  );

  if (uploadFields.length === 0) {
    throw new Error(
      "Missing upload field descriptors for create_hero_product_1",
    );
  }

  return uploadFields.map((field) => ({
    key: field.key,
    label: field.label,
    required: field.required,
  }));
}

/**
 * Situation → Decision plan review for `create_hero_product_1` (ADR-055
 * items 1, 8, 13; scope cuts per item 14 — no risks display, no
 * decision-options editing), plus the workflow's defining exception: the
 * "needs you" upload section (item 12).
 *
 * Juli pre-commits everything it can — category, attributes, brand, SEO
 * copy, price, warehouse — but it cannot propose the shop's product photos
 * and does not generate placeholder assets. Those two fields render as plain
 * uploads in a visible section, and the plan states that approval waits on
 * the seller: this workflow is deliberately not one-tap approvable.
 *
 * There is no branch discriminator, so `details` is absent, and no
 * class-D reassurance caveat exists for this workflow (item 19 excludes it
 * from repeat consent through the upload exception itself, not through
 * authored copy) — no trust line is invented to fill that gap.
 */
export function getCreateHeroProductPlanReview(): PlanReviewContent {
  return {
    workflowKey: CREATE_HERO_PRODUCT_WORKFLOW_KEY,
    title: createHeroProductFixture.title,
    situation: {
      summary: "Sản phẩm mới ngành chăm sóc da · 3 thông tin",
      disclosureQuestion: "Juli dựa vào thông tin nào?",
      detailLines: [
        "Juli đang theo dõi nhu cầu ngành chăm sóc da — nhóm này đang tăng nhưng shop chưa có sản phẩm nào đáp ứng.",
        "Danh mục Chăm sóc da / Serum (700648) với thuộc tính bắt buộc đã được xác định sẵn.",
        "Kho giao hàng WH-HCM-01 — Kho HCM đã được gán cho sản phẩm mới.",
      ],
      analyticsMetricHref: buildAnalyticsMetricHref(
        defaultCreateHeroProductAnalyticsMetricKey,
      ),
    },
    // The tied Main KPI is the workflow's existing `analyticsMetricKey`
    // binding — GMV for create_hero_product_1 (ADR-055 item 15). Nothing new
    // is mapped here, and no magnitude is projected (item 16).
    impact: buildPlanImpact(defaultCreateHeroProductAnalyticsMetricKey),
    decision: {
      proposal:
        "Juli đề xuất tạo sản phẩm “Serum dưỡng ẩm chống lão hoá cho da nhạy cảm” với giá 289.000 ₫ để lấp khoảng trống nhu cầu trong ngành chăm sóc da.",
      // The workflow's pre-authored reasoning from the shared fixture table —
      // revealed behind the question-labelled disclosure, sanitized at render.
      reasoning: createHeroProductFixture.reasoning,
      // Typed caveats, not the concatenated known-limits blob (ADR-055 item
      // 10). Both of this workflow's caveats are hidden classes, so nothing
      // of them reaches the seller — which is the point.
      caveats: getPlanCaveats(CREATE_HERO_PRODUCT_WORKFLOW_KEY),
    },
    // No `details` key: create_hero_product_1 has no branch discriminator, so
    // the Details section renders as nothing — never an empty stub.
    needsYou: {
      title: "Cần bạn bổ sung",
      // Why Juli cannot propose here, and what happens next — never a bare
      // pair of blank required fields (empty-states principle).
      explanation:
        "Ảnh sản phẩm là của shop, nên Juli không tự tạo hay đề xuất ảnh thay bạn. Khi bạn thêm ảnh, nút phê duyệt sẽ mở và Juli tạo sản phẩm với các thông tin đã chuẩn bị.",
      uploadFields: buildNeedsYouUploadFields(),
      approvalBlockedText:
        "Phê duyệt sẽ mở sau khi bạn thêm ảnh sản phẩm.",
    },
  };
}
