import type { ReviewStageContent } from "@juli/contracts";

import { recommendationFixtures } from "../../recommendations";

export const CREATE_ACTIVITY_WORKFLOW_KEY = "create_activity_7a";
export const CREATE_ACTIVITY_TOOL_NAME = "promotion.create_activity";
export const defaultCreateActivityAnalyticsMetricKey = "revenue-by-sku";

const FBT_PROMOTION_SCAFFOLD_UNFILLED =
  "FBT (giao hàng do TikTok quản lý): khung luồng khuyến mãi mục tiêu chưa được điền — Unresolved/Unfilled. Không suy diễn parity từ FBS.";

const createActivityFixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === CREATE_ACTIVITY_WORKFLOW_KEY,
);

if (!createActivityFixtureEntry) {
  throw new Error("Missing create_activity_7a recommendation fixture");
}

const createActivityFixture = createActivityFixtureEntry;

export function buildCreateActivityReviewInputDefaults(): Record<string, string> {
  return {
    activity_type: "",
    skus: "PRD-77201 — Serum dưỡng ẩm; PRD-77202 — Kem chống nắng SPF50",
    discount_config: "",
    promotion_start_date: "",
    promotion_end_date: "",
  };
}

export function getCreateActivityReviewStages(
  analyticsMetricKey = defaultCreateActivityAnalyticsMetricKey,
): ReviewStageContent[] {
  const analyticsMetricHref = `/analytics/${analyticsMetricKey}`;

  return [
    {
      stage: "why",
      title: "Vì sao đề xuất này",
      body: [
        createActivityFixture.reasoning,
        createActivityFixture.signal,
        createActivityFixture.evidence,
        createActivityFixture.risks,
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
        "Loại khuyến mãi, SKU, giá/giảm giá và cửa sổ thời gian cần shop xác nhận — không có số tiền giảm giá mặc định.",
        "SKU được điền sẵn từ tín hiệu; shop có thể bỏ SKU không muốn tham gia.",
        "Ngưỡng tăng trưởng/hiệu suất để tạo đề xuất này chưa được xác định.",
      ].join(" "),
      inputFields: [
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
          prefillValue:
            "PRD-77201 — Serum dưỡng ẩm; PRD-77202 — Kem chống nắng SPF50",
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
        `Công cụ: ${createActivityFixture.toolName}`,
        `Khả năng: ${createActivityFixture.capabilityLabel}`,
        `Điều kiện: ${createActivityFixture.eligibility}`,
        createActivityFixture.knownLimits,
        FBT_PROMOTION_SCAFFOLD_UNFILLED,
      ].join("\n\n"),
    },
    {
      stage: "approve",
      title: "Xác nhận phê duyệt",
      body:
        "Phê duyệt sẽ ghi nhận workflow_key và tool_name, sau đó mở luồng Đang thực hiện. Demo không gọi TikTok API thật; chỉ luồng FBS được hỗ trợ thực thi.",
    },
  ];
}
