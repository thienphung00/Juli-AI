import type { ReviewStageContent } from "@juli/contracts";

import { recommendationFixtures } from "../../recommendations";

export const UPDATE_ACTIVITY_WORKFLOW_KEY = "update_activity_7c";
export const UPDATE_ACTIVITY_TOOL_NAME = "promotion.update_activity";
export const defaultUpdateActivityAnalyticsMetricKey = "revenue-by-sku";

const FBT_PROMOTION_SCAFFOLD_UNFILLED =
  "FBT (giao hàng do TikTok quản lý): khung luồng khuyến mãi mục tiêu chưa được điền — Unresolved/Unfilled. Không suy diễn parity từ FBS.";

const updateActivityFixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === UPDATE_ACTIVITY_WORKFLOW_KEY,
);

if (!updateActivityFixtureEntry) {
  throw new Error("Missing update_activity_7c recommendation fixture");
}

const updateActivityFixture = updateActivityFixtureEntry;

export function buildUpdateActivityReviewInputDefaults(): Record<string, string> {
  return {
    activity_id: "ACT-8842",
    activity_type: "",
    skus: "PRD-77201 — Serum dưỡng ẩm",
    discount_config: "",
    promotion_start_date: "",
    promotion_end_date: "",
  };
}

export function getUpdateActivityReviewStages(
  analyticsMetricKey = defaultUpdateActivityAnalyticsMetricKey,
): ReviewStageContent[] {
  const analyticsMetricHref = `/analytics/${analyticsMetricKey}`;

  return [
    {
      stage: "why",
      title: "Vì sao đề xuất này",
      body: [
        updateActivityFixture.reasoning,
        updateActivityFixture.signal,
        updateActivityFixture.evidence,
        updateActivityFixture.risks,
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
        "Loại khuyến mãi, SKU, giá/giảm giá và cửa sổ thời gian cần shop xác nhận — không có số tiền giảm giá mặc định.",
        "Webhook Activity change (#63) cho chỉnh cấu hình được catalog nhưng hỗ trợ hiển thị là chưa xác định nếu môi trường hiện tại chưa đăng ký.",
      ].join(" "),
      inputFields: [
        {
          key: "activity_id",
          label: "Chương trình khuyến mãi",
          prefillValue: "ACT-8842 — Flash Sale chăm sóc da (đang hoạt động)",
          required: true,
          editable: false,
        },
        {
          key: "activity_type",
          label: "Loại khuyến mãi",
          prefillValue: "",
          required: true,
          editable: true,
        },
        {
          key: "skus",
          label: "SKU tham gia",
          prefillValue: "PRD-77201 — Serum dưỡng ẩm",
          required: true,
          editable: true,
        },
        {
          key: "discount_config",
          label: "Giá/giảm giá",
          prefillValue: "",
          required: true,
          editable: true,
        },
        {
          key: "promotion_start_date",
          label: "Ngày bắt đầu",
          prefillValue: "",
          required: true,
          editable: true,
        },
        {
          key: "promotion_end_date",
          label: "Ngày kết thúc",
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
        `Công cụ: ${updateActivityFixture.toolName}`,
        `Khả năng: ${updateActivityFixture.capabilityLabel}`,
        `Điều kiện: ${updateActivityFixture.eligibility}`,
        updateActivityFixture.knownLimits,
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
