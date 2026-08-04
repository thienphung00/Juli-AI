import type { ReviewStageContent } from "@juli/contracts";

import { recommendationFixtures } from "../../recommendations";
import {
  buildSellerApproveBody,
  buildSellerWhyBody,
  buildSellerPreviewBody,
} from "../../review-seller-copy";

export const PROCESS_ORDER_WORKFLOW_KEY = "process_order_5";
export const PROCESS_ORDER_TOOL_NAME = "fulfillment.process_order";
export const PROCESS_ORDER_FBT_INTAKE_KEY = "process_order_5b";

export const defaultProcessOrderAnalyticsMetricKey = "cancellation-rate";

const processOrderFixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === PROCESS_ORDER_WORKFLOW_KEY,
);

if (!processOrderFixtureEntry) {
  throw new Error("Missing process_order_5 recommendation fixture");
}

const processOrderFixture = processOrderFixtureEntry;

export function buildProcessOrderReviewInputDefaults(): Record<string, string> {
  return {
    order_priority: "Hàng đợi T5 — 6 đơn (chỉ đọc theo thứ hạng)",
    shipping_type: "Ship by TikTok",
    document_type: "",
    pickup_slot: "",
    tracking_number: "",
    shipping_provider_id: "",
    split_combine: "Tắt — chỉ bật khi ràng buộc đóng gói yêu cầu",
  };
}

export function getProcessOrderReviewStages(
  analyticsMetricKey = defaultProcessOrderAnalyticsMetricKey,
): ReviewStageContent[] {
  const analyticsMetricHref = `/analytics/${analyticsMetricKey}`;

  return [
    {
      stage: "why",
      title: "Vì sao đề xuất này",
      body: buildSellerWhyBody(processOrderFixture),
    },
    {
      stage: "analytics",
      title: "Bằng chứng từ Phân tích",
      body:
        "Xem KPI Tỷ lệ hủy đơn trên Phân tích để hiểu thêm bối cảnh trước khi phê duyệt. Demo không nhân bản báo cáo tại đây.",
      analyticsMetricKey,
      analyticsMetricHref,
    },
    {
      stage: "inputs",
      title: "Thông tin cần xác nhận",
      body: [
        "Thứ tự ưu tiên đơn hàng mặc định theo thứ hạng T5 và chỉ đọc.",
        "Loại vận chuyển mặc định từ đơn hàng — Ship by TikTok và Ship by Seller loại trừ lẫn nhau theo gói.",
        "Ship by TikTok cần loại tài liệu/lấy hàng được hợp đồng hỗ trợ; Ship by Seller cần mã vận đơn và mã nhà vận chuyển do shop nhập.",
        "Tách/gộp gói mặc định tắt — chỉ hiện khi ràng buộc đóng gói yêu cầu.",
      ].join(" "),
      inputFields: [
        {
          key: "order_priority",
          label: "Thứ tự ưu tiên đơn hàng (T5)",
          prefillValue: "Hàng đợi T5 — 6 đơn (chỉ đọc theo thứ hạng)",
          required: true,
          editable: false,
        },
        {
          key: "shipping_type",
          label: "Loại vận chuyển",
          prefillValue: "Ship by TikTok — từ đơn hàng",
          required: true,
          editable: true,
        },
        {
          key: "document_type",
          label: "Loại tài liệu vận chuyển (Ship by TikTok)",
          prefillValue: "",
          required: false,
          editable: true,
        },
        {
          key: "pickup_slot",
          label: "Khung lấy hàng (Ship by TikTok)",
          prefillValue: "",
          required: false,
          editable: true,
        },
        {
          key: "tracking_number",
          label: "Mã vận đơn (Ship by Seller)",
          prefillValue: "",
          required: false,
          editable: true,
        },
        {
          key: "shipping_provider_id",
          label: "Mã nhà vận chuyển (Ship by Seller)",
          prefillValue: "",
          required: false,
          editable: true,
        },
        {
          key: "split_combine",
          label: "Tách/gộp gói",
          prefillValue: "Tắt — chỉ bật khi ràng buộc đóng gói yêu cầu",
          required: false,
          editable: true,
        },
      ],
    },
    {
      stage: "preview",
      title: "Xem trước trước khi phê duyệt",
      body: buildSellerPreviewBody(processOrderFixture, [
        "Juli sẽ ưu tiên đơn theo thứ tự đã xếp hạng, đóng gói và giao theo loại vận chuyển bạn xác nhận.",
        "Ngưỡng thời gian chính xác để tạo đề xuất này chưa được xác định.",
      ]),
    },
    {
      stage: "approve",
      title: "Xác nhận phê duyệt",
      body: buildSellerApproveBody([
        "Demo không tạo hoặc giao lô hàng khi đơn đang tạm giữ.",
      ]),
    },
  ];
}
