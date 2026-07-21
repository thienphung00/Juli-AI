import type { ReviewStageContent } from "@juli/contracts";

import { recommendationFixtures } from "../../recommendations";

export const OPTIMIZE_PRODUCT_WORKFLOW_KEY = "optimize_product_2";
export const OPTIMIZE_PRODUCT_TOOL_NAME = "listing.optimize_product";
export const defaultOptimizeProductAnalyticsMetricKey = "revenue-by-sku";

const optimizeFixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === OPTIMIZE_PRODUCT_WORKFLOW_KEY,
);

if (!optimizeFixtureEntry) {
  throw new Error("Missing optimize_product_2 recommendation fixture");
}

const optimizeFixture = optimizeFixtureEntry;

export function buildOptimizeProductReviewInputDefaults(): Record<string, string> {
  return {
    product_id: "PRD-88421",
    seo_title: "Son môi lì cao cấp số 12 — màu đỏ ruby",
    seo_description:
      "Son môi lì lâu trôi, dưỡng ẩm môi, phù hợp trang điểm hàng ngày.",
    main_images: "",
    supporting_file: "",
    price: "159000",
  };
}

export function getOptimizeProductReviewStages(
  analyticsMetricKey = defaultOptimizeProductAnalyticsMetricKey,
): ReviewStageContent[] {
  const analyticsMetricHref = `/analytics/${analyticsMetricKey}`;

  return [
    {
      stage: "why",
      title: "Vì sao đề xuất này",
      body: [
        optimizeFixture.reasoning,
        optimizeFixture.signal,
        optimizeFixture.evidence,
        optimizeFixture.risks,
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
        "Giá trị hiện tại được tải từ Get Product; tiêu đề/mô tả SEO điền sẵn từ gợi ý TikTok.",
        "Thay ảnh/tệp mặc định tắt — chỉ bật khi shop chọn thay thế hoặc bổ sung.",
        "Giá theo khuyến nghị T9 trong giới hạn sàn lợi nhuận đã cấu hình; mọi trường thay đổi vẫn có thể chỉnh trước khi phê duyệt.",
      ].join(" "),
      inputFields: [
        {
          key: "product_id",
          label: "Sản phẩm",
          prefillValue: "PRD-88421 — Son môi số 12",
          required: true,
          editable: false,
        },
        {
          key: "seo_title",
          label: "Tiêu đề SEO",
          prefillValue: "Son môi lì cao cấp số 12 — màu đỏ ruby",
          required: true,
          editable: true,
        },
        {
          key: "seo_description",
          label: "Mô tả SEO",
          prefillValue:
            "Son môi lì lâu trôi, dưỡng ẩm môi, phù hợp trang điểm hàng ngày.",
          required: true,
          editable: true,
        },
        {
          key: "main_images",
          label: "Ảnh sản phẩm (thay thế/bổ sung)",
          prefillValue: "",
          required: false,
          editable: true,
        },
        {
          key: "supporting_file",
          label: "Tệp hỗ trợ (nếu danh mục yêu cầu)",
          prefillValue: "",
          required: false,
          editable: true,
        },
        {
          key: "price",
          label: "Giá bán (T9)",
          prefillValue: "159.000 ₫",
          required: true,
          editable: true,
        },
      ],
    },
    {
      stage: "preview",
      title: "Xem trước trước khi phê duyệt",
      body: [
        `Công cụ: ${optimizeFixture.toolName}`,
        `Khả năng: ${optimizeFixture.capabilityLabel}`,
        `Điều kiện: ${optimizeFixture.eligibility}`,
        optimizeFixture.knownLimits,
        "Giá phải ở trên mức sàn lợi nhuận đã cấu hình — thay đổi dưới sàn sẽ bị chặn khi phê duyệt.",
        "Khung FBT (giao hàng do TikTok quản lý) cho tối ưu sản phẩm chưa được điền — không suy diễn luồng FBS hợp lệ cho ghi danh FBT.",
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
