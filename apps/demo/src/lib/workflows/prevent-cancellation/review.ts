import type { ReviewStageContent } from "@juli/contracts";

import { recommendationFixtures } from "../../recommendations";

export const PREVENT_CANCELLATION_WORKFLOW_KEY = "prevent_cancellation_8a";
export const PREVENT_CANCELLATION_TOOL_NAME = "returns.prevent_cancellation";

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
    seller_decision: "",
    reject_reason: "",
  };
}

export function getPreventCancellationReviewStages(
  analyticsMetricKey = "net-revenue",
): ReviewStageContent[] {
  const analyticsMetricHref = `/analytics/${analyticsMetricKey}`;

  return [
    {
      stage: "why",
      title: "Vì sao đề xuất này",
      body: [
        preventCancellationFixture.reasoning,
        preventCancellationFixture.signal,
        preventCancellationFixture.evidence,
        preventCancellationFixture.risks,
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
      body: [
        `Công cụ: ${preventCancellationFixture.toolName}`,
        `Khả năng: ${preventCancellationFixture.capabilityLabel}`,
        `Điều kiện: ${preventCancellationFixture.eligibility}`,
        preventCancellationFixture.knownLimits,
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
