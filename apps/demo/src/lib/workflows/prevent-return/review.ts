import type { ReviewStageContent } from "@juli/contracts";

import { recommendationFixtures } from "../../recommendations";

export const PREVENT_RETURN_WORKFLOW_KEY = "prevent_return_8b";
export const PREVENT_RETURN_FBT_INTAKE_KEY = "prevent_return_8b_fbt";
export const PREVENT_RETURN_TOOL_NAME = "returns.prevent_return";

const preventReturnFixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === PREVENT_RETURN_WORKFLOW_KEY,
);

if (!preventReturnFixtureEntry) {
  throw new Error("Missing prevent_return_8b recommendation fixture");
}

const preventReturnFixture = preventReturnFixtureEntry;

export function buildPreventReturnReviewInputDefaults(): Record<string, string> {
  return {
    return_id: "RT-33190",
    order_id: "ORD-44102",
    return_reason: "Sản phẩm không đúng mô tả",
    decision_deadline: "2026-07-20 12:00",
    rma_state: "Đang chờ hàng về kho FBS",
    risk_evidence: "Quy tắc: lần trả đầu — không có điểm ML giả",
    seller_decision: "",
    reject_reason: "",
    review_notes: "",
    restock_enabled: "off",
    resellable_quantity: "",
  };
}

export function getPreventReturnReviewStages(
  analyticsMetricKey = "net-revenue",
): ReviewStageContent[] {
  const analyticsMetricHref = `/analytics/${analyticsMetricKey}`;

  return [
    {
      stage: "why",
      title: "Vì sao đề xuất này",
      body: [
        preventReturnFixture.reasoning,
        preventReturnFixture.signal,
        preventReturnFixture.evidence,
        preventReturnFixture.risks,
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
        "Không có mặc định Phê duyệt/Từ chối. Nhập lại kho FBS mặc định tắt đến khi kiểm tra thực tế; số lượng còn bán được cần nhập tường minh. Luồng FBT (prevent_return_8b_fbt) chỉ ghi nhận — không thực thi tại đây.",
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
          prefillValue: "Đang chờ hàng về kho FBS",
          required: true,
          editable: false,
        },
        {
          key: "risk_evidence",
          label: "Bằng chứng rủi ro (theo quy tắc)",
          prefillValue: "Quy tắc: lần trả đầu — không có điểm ML giả",
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
          label: "Nhập lại kho FBS sau kiểm tra",
          prefillValue: "off",
          required: true,
          editable: true,
        },
        {
          key: "resellable_quantity",
          label: "Số lượng còn bán được (sau kiểm tra)",
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
        `Công cụ: ${preventReturnFixture.toolName}`,
        `Khả năng: ${preventReturnFixture.capabilityLabel}`,
        `Điều kiện: ${preventReturnFixture.eligibility}`,
        preventReturnFixture.knownLimits,
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
