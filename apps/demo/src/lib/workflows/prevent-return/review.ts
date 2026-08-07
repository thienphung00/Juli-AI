import type { ReviewStageContent } from "@juli/contracts";

import { recommendationFixtures } from "../../recommendations";
import {
  buildSellerApproveBody,
  buildSellerWhyBody,
  buildSellerPreviewBody,
} from "../../review-seller-copy";

export const PREVENT_RETURN_WORKFLOW_KEY = "prevent_return_8b";
export const PREVENT_RETURN_FBT_INTAKE_KEY = "prevent_return_8b_fbt";
export const PREVENT_RETURN_TOOL_NAME = "returns.prevent_return";

/**
 * The Main KPI this workflow's decision is tied to — GMV (ADR-055 item 15).
 * A return decided in time is revenue the shop either keeps or releases
 * cleanly; nothing new is mapped here.
 */
export const defaultPreventReturnAnalyticsMetricKey = "gmv-tiktok";

const preventReturnFixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === PREVENT_RETURN_WORKFLOW_KEY,
);

if (!preventReturnFixtureEntry) {
  throw new Error("Missing prevent_return_8b recommendation fixture");
}

const preventReturnFixture = preventReturnFixtureEntry;

/**
 * Seller-facing defaults for the approval flow.
 *
 * `resellable_quantity` ("Số lượng còn bán được (sau kiểm tra)") is
 * deliberately absent: it describes an outcome that only exists **after
 * inspection**, so no seller can answer it at approve time (ADR-055 Context;
 * issue #769). It is removed from the approval flow entirely — not hidden, not
 * disabled, not optional. Execution does not read it either; the run's
 * inspection-result step belongs to a later lifecycle moment.
 */
export function buildPreventReturnReviewInputDefaults(): Record<string, string> {
  return {
    return_id: "RT-33190",
    order_id: "ORD-44102",
    return_reason: "Sản phẩm không đúng mô tả",
    decision_deadline: "2026-07-20 12:00",
    rma_state: "Đang chờ hàng về kho",
    risk_evidence: "Quy tắc: lần trả đầu — không có dấu hiệu gian lận",
    seller_decision: "Phê duyệt",
    reject_reason: "",
    review_notes: "Khách hàng yêu cầu hoàn tiền, chúng tôi đồng ý",
    restock_enabled: "off",
  };
}

export function getPreventReturnReviewStages(
  analyticsMetricKey = defaultPreventReturnAnalyticsMetricKey,
): ReviewStageContent[] {
  const analyticsMetricHref = `/analytics/${analyticsMetricKey}`;

  return [
    {
      stage: "why",
      title: "Vì sao đề xuất này",
      body: buildSellerWhyBody(preventReturnFixture),
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
        "Không có mặc định Phê duyệt/Từ chối. Nhập lại kho mặc định tắt đến khi kiểm tra thực tế. Luồng trả hàng qua giao hàng do TikTok quản lý chỉ ghi nhận — không thực thi tại đây.",
      inputFields: [
        {
          key: "return_id",
          label: "Mã yêu cầu trả hàng",
          prefillValue: "RT-33190",
          required: true,
          editable: false,
        },
        {
          key: "order_id",
          label: "Mã đơn hàng",
          prefillValue: "ORD-44102",
          required: true,
          editable: false,
        },
        {
          key: "return_reason",
          label: "Lý do trả hàng",
          prefillValue: "Sản phẩm không đúng mô tả",
          required: true,
          editable: false,
        },
        {
          key: "decision_deadline",
          label: "Hạn quyết định",
          prefillValue: "2026-07-20 12:00",
          required: true,
          editable: false,
        },
        {
          key: "rma_state",
          label: "Trạng thái RMA",
          prefillValue: "Đang chờ hàng về kho",
          required: true,
          editable: false,
        },
        {
          key: "risk_evidence",
          label: "Bằng chứng rủi ro (theo quy tắc)",
          prefillValue: "Quy tắc: lần trả đầu — không có dấu hiệu gian lận",
          required: false,
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
        {
          key: "review_notes",
          label: "Ghi chú xem xét (khi leo thang)",
          prefillValue: "",
          required: false,
          editable: true,
        },
        {
          key: "restock_enabled",
          label: "Nhập lại kho sau kiểm tra",
          prefillValue: "off",
          required: true,
          editable: true,
        },
        // No `resellable_quantity` field: it is post-execution ("sau kiểm
        // tra") and is not collected at approve time (issue #769).
      ],
    },
    {
      stage: "preview",
      title: "Xem trước trước khi phê duyệt",
      body: buildSellerPreviewBody(preventReturnFixture),
    },
    {
      stage: "approve",
      title: "Xác nhận phê duyệt",
      body: buildSellerApproveBody(),
    },
  ];
}
