import type { ReviewStageContent } from "@juli/contracts";

import { recommendationFixtures } from "../../recommendations";
import {
  buildSellerApproveBody,
  buildSellerWhyBody,
  buildSellerPreviewBody,
} from "../../review-seller-copy";

export const PREVENT_CANCELLATION_WORKFLOW_KEY = "prevent_cancellation_8a";
export const PREVENT_CANCELLATION_TOOL_NAME = "returns.prevent_cancellation";

/**
 * The Main KPI this workflow's decision is tied to — GMV (ADR-055 item 15).
 * Deciding a cancellation before the deadline is what keeps or releases the
 * order's revenue; nothing new is mapped here.
 */
export const defaultPreventCancellationAnalyticsMetricKey = "gmv-tiktok";

const preventCancellationFixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === PREVENT_CANCELLATION_WORKFLOW_KEY,
);

if (!preventCancellationFixtureEntry) {
  throw new Error("Missing prevent_cancellation_8a recommendation fixture");
}

const preventCancellationFixture = preventCancellationFixtureEntry;

export function buildPreventCancellationReviewInputDefaults(): Record<
  string,
  string
> {
  return {
    cancel_id: "CN-88421",
    order_id: "ORD-55210",
    buyer_reason: "Đổi ý trước khi giao",
    decision_deadline: "2026-07-18 17:00",
    eligibility: "Còn trong cửa sổ quyết định trước giao hàng",
    seller_decision: "Phê duyệt",
    reject_reason: "",
  };
}

export function getPreventCancellationReviewStages(
  analyticsMetricKey = defaultPreventCancellationAnalyticsMetricKey,
): ReviewStageContent[] {
  const analyticsMetricHref = `/analytics/${analyticsMetricKey}`;

  return [
    {
      stage: "why",
      title: "Vì sao đề xuất này",
      body: buildSellerWhyBody(preventCancellationFixture),
    },
    {
      stage: "analytics",
      title: "Bằng chứng từ Phân tích",
      body:
        "Xem KPI liên quan trên Phân tích để hiểu thêm bối cảnh trước khi phê duyệt. Demo không nhân bản báo cáo tại đây.",
      analyticsMetricKey,
      analyticsMetricHref,
    },
    {
      stage: "inputs",
      title: "Thông tin cần xác nhận",
      body:
        "Mã yêu cầu/đơn và điều kiện là chỉ đọc. Shop phải chọn Phê duyệt hoặc Từ chối — không có mặc định. Lý do từ chối lấy từ danh sách chính thức, không tự điền.",
      inputFields: [
        {
          key: "cancel_id",
          label: "Mã yêu cầu huỷ",
          prefillValue: "CN-88421",
          required: true,
          editable: false,
        },
        {
          key: "order_id",
          label: "Mã đơn hàng",
          prefillValue: "ORD-55210",
          required: true,
          editable: false,
        },
        {
          key: "buyer_reason",
          label: "Lý do người mua",
          prefillValue: "Đổi ý trước khi giao",
          required: true,
          editable: false,
        },
        {
          key: "decision_deadline",
          label: "Hạn quyết định",
          prefillValue: "2026-07-18 17:00",
          required: true,
          editable: false,
        },
        {
          key: "eligibility",
          label: "Điều kiện quyết định",
          prefillValue: "Còn trong cửa sổ quyết định trước giao hàng",
          required: true,
          editable: false,
        },
        {
          key: "seller_decision",
          label: "Quyết định của shop (Phê duyệt / Từ chối)",
          prefillValue: "",
          required: true,
          editable: true,
        },
        {
          key: "reject_reason",
          label: "Lý do từ chối (bắt buộc nếu Từ chối)",
          prefillValue: "",
          required: false,
          editable: true,
        },
      ],
    },
    {
      stage: "preview",
      title: "Xem trước trước khi phê duyệt",
      body: buildSellerPreviewBody(preventCancellationFixture),
    },
    {
      stage: "approve",
      title: "Xác nhận phê duyệt",
      body: buildSellerApproveBody(),
    },
  ];
}
