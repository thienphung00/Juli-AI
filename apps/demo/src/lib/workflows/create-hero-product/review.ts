import type { ReviewStageContent } from "@juli/contracts";

import { recommendationFixtures } from "../../recommendations";
import {
  buildSellerApproveBody,
  buildSellerPreviewBody,
  buildSellerWhyBody,
} from "../../review-seller-copy";

export const CREATE_HERO_PRODUCT_WORKFLOW_KEY = "create_hero_product_1";
export const CREATE_HERO_PRODUCT_TOOL_NAME = "listing.create_hero_product";
export const defaultCreateHeroProductAnalyticsMetricKey = "gmv-tiktok";

const createHeroProductFixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === CREATE_HERO_PRODUCT_WORKFLOW_KEY,
);

if (!createHeroProductFixtureEntry) {
  throw new Error("Missing create_hero_product_1 recommendation fixture");
}

export const createHeroProductFixture = createHeroProductFixtureEntry;

export function buildCreateHeroProductReviewInputDefaults(): Record<
  string,
  string
> {
  return {
    category_id: "700648",
    attributes: "Loại da:Nhạy cảm;Dung tích:30ml",
    brand_id: "BR-1024",
    main_images: "",
    supporting_file: "",
    seo_title: "Serum dưỡng ẩm chống lão hoá cho da nhạy cảm",
    seo_description:
      "Serum dưỡng ẩm giúp cân bằng độ ẩm, hỗ trợ hàng rào da nhạy cảm.",
    price: "289000",
    warehouse_id: "WH-HCM-01",
  };
}

export function getCreateHeroProductReviewStages(
  analyticsMetricKey = defaultCreateHeroProductAnalyticsMetricKey,
): ReviewStageContent[] {
  const analyticsMetricHref = `/analytics/${analyticsMetricKey}`;

  return [
    {
      stage: "why",
      title: "Vì sao đề xuất này",
      body: buildSellerWhyBody(createHeroProductFixture),
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
        "Danh mục và thuộc tính được điền sẵn từ dữ liệu catalog; nhãn hiệu cần khớp đã xác nhận; ảnh do shop tải lên; giá theo khuyến nghị T9; kho giao hàng phải được gán.",
      inputFields: [
        {
          key: "category_id",
          label: "Danh mục",
          prefillValue: "700648 — Chăm sóc da / Serum",
          required: true,
          editable: false,
        },
        {
          key: "attributes",
          label: "Thuộc tính bắt buộc",
          prefillValue: "Loại da:Nhạy cảm; Dung tích:30ml",
          required: true,
          editable: true,
        },
        {
          key: "brand_id",
          label: "Nhãn hiệu",
          prefillValue: "BR-1024 — Juli Skin Lab (đã khớp)",
          required: true,
          editable: true,
        },
        {
          key: "main_images",
          label: "Ảnh sản phẩm",
          prefillValue: "",
          required: true,
          editable: true,
          kind: "upload",
        },
        {
          key: "supporting_file",
          label: "Tệp hỗ trợ (nếu danh mục yêu cầu)",
          prefillValue: "",
          required: false,
          editable: true,
          kind: "upload",
        },
        {
          key: "seo_title",
          label: "Tiêu đề SEO",
          prefillValue:
            "Serum dưỡng ẩm chống lão hoá cho da nhạy cảm",
          required: true,
          editable: true,
        },
        {
          key: "seo_description",
          label: "Mô tả SEO",
          prefillValue:
            "Serum dưỡng ẩm giúp cân bằng độ ẩm, hỗ trợ hàng rào da nhạy cảm.",
          required: true,
          editable: true,
        },
        {
          key: "price",
          label: "Giá bán (T9)",
          prefillValue: "289.000 ₫",
          required: true,
          editable: true,
        },
        {
          key: "warehouse_id",
          label: "Kho giao hàng",
          prefillValue: "WH-HCM-01 — Kho HCM (đã gán)",
          required: true,
          editable: false,
        },
      ],
    },
    {
      stage: "preview",
      title: "Xem trước trước khi phê duyệt",
      body: buildSellerPreviewBody(createHeroProductFixture, [
        "Shop cần đã xác thực, có đủ thuộc tính/nhãn hiệu/hình ảnh bắt buộc, và kho giao hàng đã được gán.",
        "Ngưỡng chính xác để phát hiện khoảng trống danh mục chưa được xác định — Juli không tự suy diễn con số này.",
      ]),
    },
    {
      stage: "approve",
      title: "Xác nhận phê duyệt",
      body: buildSellerApproveBody([
        "Giao hàng do TikTok quản lý cho sản phẩm mới chưa có trong Demo.",
      ]),
    },
  ];
}
