import type { ReviewStageContent } from "@juli/contracts";

import { recommendationFixtures } from "../../recommendations";

export const PREVENT_REFUND_WORKFLOW_KEY = "prevent_refund_8c";
export const PREVENT_REFUND_TOOL_NAME = "returns.prevent_refund";

const preventRefundFixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === PREVENT_REFUND_WORKFLOW_KEY,
);

if (!preventRefundFixtureEntry) {
  throw new Error("Missing prevent_refund_8c recommendation fixture");
}

const preventRefundFixture = preventRefundFixtureEntry;

export function buildPreventRefundReviewInputDefaults(): Record<string, string> {
  return {
    aftersale_id: "AS-77201",
    order_id: "ORD-33991",
    request_reason: "Hoàn tiền một phần sau khi đồng ý giảm giá",
    calculated_amount: "185000",
    refund_type: "partial",
    physical_return_linked: "Không — thuộc luồng trả hàng riêng",
    decision_deadline: "2026-07-19 09:00",
    seller_decision: "",
    reject_reason: "",
  };
}

export function getPreventRefundReviewStages(
  analyticsMetricKey = "net-revenue",
): ReviewStageContent[] {
  const analyticsMetricHref = `/analytics/${analyticsMetricKey}`;

  return [
    {
      stage: "why",
      title: "Vì sao đề xuất này",
      body: [
        preventRefundFixture.reasoning,
        preventRefundFixture.signal,
        preventRefundFixture.evidence,
        preventRefundFixture.risks,
      ].join("\n\n"),
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
        "Số tiền tính toán chỉ đọc — không ước lượng. Không có mặc định Phê duyệt/Từ chối. Nếu thiếu kết quả tính toán, không phê duyệt. Hoàn tiền không gắn hành động tồn kho (thuộc luồng trả hàng).",
      inputFields: [
        {
          key: "aftersale_id",
          label: "Mã yêu cầu hậu mãi",
          prefillValue: "AS-77201",
          required: true,
          editable: false,
        },
        {
          key: "order_id",
          label: "Mã đơn hàng",
          prefillValue: "ORD-33991",
          required: true,
          editable: false,
        },
        {
          key: "request_reason",
          label: "Lý do yêu cầu",
          prefillValue: "Hoàn tiền một phần sau khi đồng ý giảm giá",
          required: true,
          editable: false,
        },
        {
          key: "calculated_amount",
          label: "Số tiền tính toán (₫)",
          prefillValue: "185000",
          required: true,
          editable: false,
        },
        {
          key: "refund_type",
          label: "Loại hoàn tiền",
          prefillValue: "partial",
          required: true,
          editable: false,
        },
        {
          key: "physical_return_linked",
          label: "Có trả hàng vật lý kèm theo",
          prefillValue: "Không — thuộc luồng trả hàng riêng",
          required: true,
          editable: false,
        },
        {
          key: "decision_deadline",
          label: "Hạn quyết định",
          prefillValue: "2026-07-19 09:00",
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
      body: [
        `Công cụ: ${preventRefundFixture.toolName}`,
        `Khả năng: ${preventRefundFixture.capabilityLabel}`,
        `Điều kiện: ${preventRefundFixture.eligibility}`,
        preventRefundFixture.knownLimits,
      ].join("\n\n"),
    },
    {
      stage: "approve",
      title: "Xác nhận phê duyệt",
      body:
        "Phê duyệt sẽ ghi nhận workflow_key và tool_name, sau đó mở luồng Đang thực hiện. Demo không gọi TikTok API thật.",
    },
  ];
}
