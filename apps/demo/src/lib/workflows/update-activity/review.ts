import type { ReviewStageContent } from "@juli/contracts";

import { recommendationFixtures } from "../../recommendations";
import {
  buildSellerApproveBody,
  buildSellerWhyBody,
  buildSellerPreviewBody,
} from "../../review-seller-copy";

export const UPDATE_ACTIVITY_WORKFLOW_KEY = "update_activity_7c";
export const UPDATE_ACTIVITY_TOOL_NAME = "promotion.update_activity";
export const defaultUpdateActivityAnalyticsMetricKey = "revenue-by-sku";

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
      body: buildSellerWhyBody(updateActivityFixture),
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
        "Chương trình khuyến mãi đã biết được tải sẵn — không hỗ trợ tìm kiếm chương trình khuyến mãi.",
        "Loại khuyến mãi, SKU, giá/giảm giá và cửa sổ thời gian cần shop xác nhận — không có số tiền giảm giá mặc định.",
        "Cập nhật cấu hình khuyến mãi phụ thuộc môi trường đã đăng ký thông báo thay đổi.",
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
      body: buildSellerPreviewBody(updateActivityFixture, [
        "Khuyến mãi mục tiêu qua giao hàng do TikTok quản lý chưa có trong Demo.",
      ]),
    },
    {
      stage: "approve",
      title: "Xác nhận phê duyệt",
      body: buildSellerApproveBody([
        "Demo không hỗ trợ tìm kiếm chương trình khuyến mãi.",
      ]),
    },
  ];
}
