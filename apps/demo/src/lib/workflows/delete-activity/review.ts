import type { ReviewStageContent } from "@juli/contracts";

import { recommendationFixtures } from "../../recommendations";
import {
  buildSellerApproveBody,
  buildSellerWhyBody,
  buildSellerPreviewBody,
} from "../../review-seller-copy";

export const DELETE_ACTIVITY_WORKFLOW_KEY = "delete_activity_7b";
export const DELETE_ACTIVITY_TOOL_NAME = "promotion.delete_activity";
export const defaultDeleteActivityAnalyticsMetricKey = "revenue-by-sku";

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
      body: buildSellerWhyBody(deleteActivityFixture),
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
        "Kết thúc chương trình không có cấu hình thêm ngoài xác nhận rõ ràng của shop.",
        "Nếu chương trình đã ngừng, bước kết thúc sẽ không thay đổi gì thêm.",
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
      body: buildSellerPreviewBody(deleteActivityFixture, [
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
