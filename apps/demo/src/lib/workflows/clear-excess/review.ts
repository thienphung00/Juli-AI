import type { ReviewStageContent } from "@juli/contracts";

import { recommendationFixtures } from "../../recommendations";
import {
  buildSellerApproveBody,
  buildSellerWhyBody,
  buildSellerPreviewBody,
} from "../../review-seller-copy";

export const CLEAR_EXCESS_WORKFLOW_KEY = "clear_excess_4";

const clearExcessFixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === CLEAR_EXCESS_WORKFLOW_KEY,
);

if (!clearExcessFixtureEntry) {
  throw new Error("Missing clear_excess_4 recommendation fixture");
}

const clearExcessFixture = clearExcessFixtureEntry;

export const defaultClearExcessAnalyticsMetricKey = "stock-health";

export function buildClearExcessReviewInputDefaults(): Record<string, string> {
  return {
    skus: "SKU-AKG-001 — Áo khoác gió mùa hè (142 đơn vị, 68 ngày tồn)",
    markdown_baseline: "",
    activity_type: "",
    promotion_start_date: "",
    promotion_end_date: "",
    flash_sale_eligibility: "Chưa kiểm tra — chờ xác minh điều kiện thật",
    zero_floor_stock_ack: "Bước sau — chưa phê duyệt trước khi xả hàng",
  };
}

export function getClearExcessReviewStages(
  analyticsMetricKey = defaultClearExcessAnalyticsMetricKey,
): ReviewStageContent[] {
  const analyticsMetricHref = `/analytics/${analyticsMetricKey}`;

  return [
    {
      stage: "why",
      title: "Vì sao đề xuất này",
      body: buildSellerWhyBody(clearExcessFixture),
    },
    {
      stage: "analytics",
      title: "Bằng chứng từ Phân tích",
      body:
        "Xem KPI Sức khỏe tồn kho trên Phân tích để hiểu thêm bối cảnh trước khi phê duyệt. Demo không nhân bản báo cáo tại đây.",
      analyticsMetricKey,
      analyticsMetricHref,
    },
    {
      stage: "inputs",
      title: "Thông tin cần xác nhận",
      body: [
        "SKU mặc định theo tín hiệu; shop có thể bỏ SKU không muốn xả.",
        "Giảm giá cơ sở và loại khuyến mãi không có giá trị số mặc định — cần shop nhập sau khi xem dữ liệu thật.",
        "Cửa sổ khuyến mãi cần ngày bắt đầu và kết thúc rõ ràng.",
        "Flash Sale chỉ chọn được sau khi có kết quả kiểm tra điều kiện thật — Demo hiển thị trạng thái chờ kiểm tra, không giả lập “đủ điều kiện”.",
        "Ngưỡng tốc độ quay vòng/tuổi hàng để kích hoạt đề xuất này chưa được xác định.",
        "Xoá tồn kho sàn về 0 là bước sau, không thể hoàn tác — chỉ thực hiện sau khi có xác nhận thực tế, không được phê duyệt ngầm ở bước này.",
      ].join("\n\n"),
      inputFields: [
        {
          key: "skus",
          label: "SKU cần xả",
          prefillValue:
            "SKU-AKG-001 — Áo khoác gió mùa hè (142 đơn vị, 68 ngày tồn)",
          required: true,
          editable: true,
        },
        {
          key: "markdown_baseline",
          label: "Giảm giá cơ sở (markdown)",
          prefillValue: "",
          required: true,
          editable: true,
        },
        {
          key: "activity_type",
          label: "Loại khuyến mãi",
          prefillValue: "",
          required: true,
          editable: true,
        },
        {
          key: "promotion_start_date",
          label: "Ngày bắt đầu khuyến mãi",
          prefillValue: "",
          required: true,
          editable: true,
        },
        {
          key: "promotion_end_date",
          label: "Ngày kết thúc khuyến mãi",
          prefillValue: "",
          required: true,
          editable: true,
        },
        {
          key: "flash_sale_eligibility",
          label: "Điều kiện Flash Sale",
          prefillValue: "Chưa kiểm tra — chờ xác minh điều kiện thật",
          required: false,
          editable: false,
        },
        {
          key: "zero_floor_stock_ack",
          label: "Xoá tồn kho sàn về 0",
          prefillValue: "Bước sau — chưa phê duyệt trước khi xả hàng",
          required: false,
          editable: false,
        },
      ],
    },
    {
      stage: "preview",
      title: "Xem trước trước khi phê duyệt",
      body: buildSellerPreviewBody(clearExcessFixture, [
        "Giao hàng do TikTok quản lý cho xả tồn chưa có trong Demo.",
      ]),
    },
    {
      stage: "approve",
      title: "Xác nhận phê duyệt",
      body: buildSellerApproveBody([
        "Demo không giả lập kết quả đủ điều kiện Flash Sale.",
      ]),
    },
  ];
}
