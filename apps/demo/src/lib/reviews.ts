import type { ReviewStageContent } from "@juli/contracts";

import { recommendationFixtures } from "./recommendations";

export const CREATE_HERO_PRODUCT_WORKFLOW_KEY = "create_hero_product_1";

const heroFixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === CREATE_HERO_PRODUCT_WORKFLOW_KEY,
);

if (!heroFixtureEntry) {
  throw new Error("Missing create_hero_product_1 recommendation fixture");
}

const heroFixture = heroFixtureEntry;

export const defaultAnalyticsMetricKey = "net-revenue";

export function buildReviewInputDefaults(): Record<string, string> {
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
    warehouse_id: "WH-FBS-HCM-01",
  };
}

export function getWorkflowReviewStages(
  workflowKey: string,
  analyticsMetricKey = defaultAnalyticsMetricKey,
): ReviewStageContent[] {
  if (workflowKey !== CREATE_HERO_PRODUCT_WORKFLOW_KEY) {
    return [];
  }

  const analyticsMetricHref = `/analytics/${analyticsMetricKey}`;

  return [
    {
      stage: "why",
      title: "Vì sao đề xuất này",
      body: [
        heroFixture.reasoning,
        heroFixture.signal,
        heroFixture.evidence,
        heroFixture.risks,
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
        "Danh mục và thuộc tính được điền sẵn từ dữ liệu catalog; nhãn hiệu cần khớp đã xác nhận; ảnh do shop tải lên; giá theo khuyến nghị T9; kho FBS phải được gán.",
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
        },
        {
          key: "supporting_file",
          label: "Tệp hỗ trợ (nếu danh mục yêu cầu)",
          prefillValue: "",
          required: false,
          editable: true,
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
          label: "Kho FBS",
          prefillValue: "WH-FBS-HCM-01 — Kho HCM (đã gán)",
          required: true,
          editable: false,
        },
      ],
    },
    {
      stage: "preview",
      title: "Xem trước trước khi phê duyệt",
      body: [
        `Công cụ: ${heroFixture.toolName}`,
        `Khả năng: ${heroFixture.capabilityLabel}`,
        `Điều kiện: ${heroFixture.eligibility}`,
        heroFixture.knownLimits,
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

export function getReviewStage(
  workflowKey: string,
  stage: ReviewStageContent["stage"],
  analyticsMetricKey = defaultAnalyticsMetricKey,
): ReviewStageContent | undefined {
  return getWorkflowReviewStages(workflowKey, analyticsMetricKey).find(
    (entry) => entry.stage === stage,
  );
}
