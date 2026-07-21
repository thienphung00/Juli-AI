import type { ReviewStageContent } from "@juli/contracts";

import { recommendationFixtures } from "../../recommendations";

export const DELETE_ACTIVITY_WORKFLOW_KEY = "delete_activity_7b";
export const DELETE_ACTIVITY_TOOL_NAME = "promotion.delete_activity";
export const defaultDeleteActivityAnalyticsMetricKey = "revenue-by-sku";

const FBT_PROMOTION_SCAFFOLD_UNFILLED =
  "FBT (giao hàng do TikTok quản lý): khung luồng khuyến mãi mục tiêu chưa được điền — Unresolved/Unfilled. Không suy diễn parity từ FBS.";

const deleteActivityFixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === DELETE_ACTIVITY_WORKFLOW_KEY,
);

if (!deleteActivityFixtureEntry) {
  throw new Error("Missing delete_activity_7b recommendation fixture");
}

const deleteActivityFixture = deleteActivityFixtureEntry;

export function buildDeleteActivityReviewInputDefaults(): Record<string, string> {
  return {
    activity_id: "ACT-7720",
    confirm_end: "",
  };
}

export function getDeleteActivityReviewStages(
  analyticsMetricKey = defaultDeleteActivityAnalyticsMetricKey,
): ReviewStageContent[] {
  const analyticsMetricHref = `/analytics/${analyticsMetricKey}`;

  return [
    {
      stage: "why",
      title: "Vì sao đề xuất này",
      body: [
        deleteActivityFixture.reasoning,
        deleteActivityFixture.signal,
        deleteActivityFixture.evidence,
        deleteActivityFixture.risks,
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
      body: [
        "activity_id đã biết được tải sẵn — không hỗ trợ tìm kiếm chương trình khuyến mãi.",
        "Kết thúc chương trình không có payload cấu hình thêm ngoài xác nhận rõ ràng của shop.",
        "Nếu activity đã inactive, luồng kết thúc như no-op.",
      ].join(" "),
      inputFields: [
        {
          key: "activity_id",
          label: "Chương trình khuyến mãi",
          prefillValue: "ACT-7720 — Giảm giá trực tiếp mùa hè (đang hoạt động)",
          required: true,
          editable: false,
        },
        {
          key: "confirm_end",
          label: "Xác nhận kết thúc chương trình",
          prefillValue: "",
          required: true,
          editable: true,
        },
      ],
    },
    {
      stage: "preview",
      title: "Xem trước trước khi phê duyệt",
      body: [
        `Công cụ: ${deleteActivityFixture.toolName}`,
        `Khả năng: ${deleteActivityFixture.capabilityLabel}`,
        `Điều kiện: ${deleteActivityFixture.eligibility}`,
        deleteActivityFixture.knownLimits,
        FBT_PROMOTION_SCAFFOLD_UNFILLED,
      ].join("\n\n"),
    },
    {
      stage: "approve",
      title: "Xác nhận phê duyệt",
      body:
        "Phê duyệt sẽ ghi nhận workflow_key và tool_name, sau đó mở luồng Đang thực hiện. Demo không gọi TikTok API thật; không hỗ trợ tìm kiếm activity.",
    },
  ];
}
