import type { ReviewStageContent } from "@juli/contracts";

import { recommendationFixtures } from "./recommendations";

export const CREATE_HERO_PRODUCT_WORKFLOW_KEY = "create_hero_product_1";
export const PREVENT_CANCELLATION_WORKFLOW_KEY = "prevent_cancellation_8a";
export const PREVENT_RETURN_WORKFLOW_KEY = "prevent_return_8b";
export const PREVENT_RETURN_FBT_INTAKE_KEY = "prevent_return_8b_fbt";
export const PREVENT_REFUND_WORKFLOW_KEY = "prevent_refund_8c";

export const REVIEW_EXECUTABLE_WORKFLOW_KEYS = [
  CREATE_HERO_PRODUCT_WORKFLOW_KEY,
  PREVENT_CANCELLATION_WORKFLOW_KEY,
  PREVENT_RETURN_WORKFLOW_KEY,
  PREVENT_REFUND_WORKFLOW_KEY,
] as const;

export function isReviewExecutableWorkflow(workflowKey: string): boolean {
  return (REVIEW_EXECUTABLE_WORKFLOW_KEYS as readonly string[]).includes(
    workflowKey,
  );
}

function requireFixture(workflowKey: string) {
  const fixture = recommendationFixtures.find(
    (entry) => entry.workflowKey === workflowKey,
  );

  if (!fixture) {
    throw new Error(`Missing recommendation fixture for ${workflowKey}`);
  }

  return fixture;
}

export const defaultAnalyticsMetricKey = "net-revenue";

const HERO_INPUT_DEFAULTS: Record<string, string> = {
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

const CANCELLATION_INPUT_DEFAULTS: Record<string, string> = {
  cancel_id: "CN-88421",
  order_id: "ORD-55210",
  buyer_reason: "Đổi ý trước khi giao",
  decision_deadline: "2026-07-18 17:00",
  eligibility: "Còn trong cửa sổ quyết định trước giao hàng",
  seller_decision: "",
  reject_reason: "",
};

const RETURN_INPUT_DEFAULTS: Record<string, string> = {
  return_id: "RT-33190",
  order_id: "ORD-44102",
  return_reason: "Sản phẩm không đúng mô tả",
  decision_deadline: "2026-07-20 12:00",
  rma_state: "Đang chờ hàng về kho FBS",
  risk_evidence: "Quy tắc: lần trả đầu — không có điểm ML giả",
  seller_decision: "",
  reject_reason: "",
  review_notes: "",
  restock_enabled: "off",
  resellable_quantity: "",
};

const REFUND_INPUT_DEFAULTS: Record<string, string> = {
  aftersale_id: "AS-77201",
  order_id: "ORD-33991",
  request_reason: "Hoàn tiền một phần sau khi đồng ý giảm giá",
  calculated_amount: "185000",
  refund_type: "partial",
  physical_return_linked: "Không — thuộc luồng trả hàng riêng",
  decision_deadline: "2026-07-19 09:00",
  seller_decision: "",
  reject_reason: "",
};

export function buildReviewInputDefaults(
  workflowKey = CREATE_HERO_PRODUCT_WORKFLOW_KEY,
): Record<string, string> {
  switch (workflowKey) {
    case PREVENT_CANCELLATION_WORKFLOW_KEY:
      return { ...CANCELLATION_INPUT_DEFAULTS };
    case PREVENT_RETURN_WORKFLOW_KEY:
      return { ...RETURN_INPUT_DEFAULTS };
    case PREVENT_REFUND_WORKFLOW_KEY:
      return { ...REFUND_INPUT_DEFAULTS };
    case CREATE_HERO_PRODUCT_WORKFLOW_KEY:
      return { ...HERO_INPUT_DEFAULTS };
    default:
      return {};
  }
}

function sharedWhyAnalyticsPreviewApprove(
  workflowKey: string,
  analyticsMetricKey: string,
  inputsStage: ReviewStageContent,
): ReviewStageContent[] {
  const fixture = requireFixture(workflowKey);
  const analyticsMetricHref = `/analytics/${analyticsMetricKey}`;

  return [
    {
      stage: "why",
      title: "Vì sao đề xuất này",
      body: [
        fixture.reasoning,
        fixture.signal,
        fixture.evidence,
        fixture.risks,
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
    inputsStage,
    {
      stage: "preview",
      title: "Xem trước trước khi phê duyệt",
      body: [
        `Công cụ: ${fixture.toolName}`,
        `Khả năng: ${fixture.capabilityLabel}`,
        `Điều kiện: ${fixture.eligibility}`,
        fixture.knownLimits,
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

function getHeroReviewStages(
  analyticsMetricKey: string,
): ReviewStageContent[] {
  return sharedWhyAnalyticsPreviewApprove(
    CREATE_HERO_PRODUCT_WORKFLOW_KEY,
    analyticsMetricKey,
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
          prefillValue: "Serum dưỡng ẩm chống lão hoá cho da nhạy cảm",
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
  );
}

function getCancellationReviewStages(
  analyticsMetricKey: string,
): ReviewStageContent[] {
  return sharedWhyAnalyticsPreviewApprove(
    PREVENT_CANCELLATION_WORKFLOW_KEY,
    analyticsMetricKey,
    {
      stage: "inputs",
      title: "Thông tin cần xác nhận",
      body:
        "Mã yêu cầu/đơn và điều kiện là chỉ đọc. Shop phải chọn Phê duyệt hoặc Từ chối — không có mặc định. Lý do từ chối lấy từ danh sách chính thức, không tự điền.",
      inputFields: [
        {
          key: "cancel_id",
          label: "Mã yêu cầu huỷ",
          prefillValue: "CN-88421",
          required: true,
          editable: false,
        },
        {
          key: "order_id",
          label: "Mã đơn hàng",
          prefillValue: "ORD-55210",
          required: true,
          editable: false,
        },
        {
          key: "buyer_reason",
          label: "Lý do người mua",
          prefillValue: "Đổi ý trước khi giao",
          required: true,
          editable: false,
        },
        {
          key: "decision_deadline",
          label: "Hạn quyết định",
          prefillValue: "2026-07-18 17:00",
          required: true,
          editable: false,
        },
        {
          key: "eligibility",
          label: "Điều kiện quyết định",
          prefillValue: "Còn trong cửa sổ quyết định trước giao hàng",
          required: true,
          editable: false,
        },
        {
          key: "seller_decision",
          label: "Quyết định của shop (Phê duyệt / Từ chối)",
          prefillValue: "",
          required: true,
          editable: true,
        },
        {
          key: "reject_reason",
          label: "Lý do từ chối (bắt buộc nếu Từ chối)",
          prefillValue: "",
          required: false,
          editable: true,
        },
      ],
    },
  );
}

function getReturnReviewStages(
  analyticsMetricKey: string,
): ReviewStageContent[] {
  return sharedWhyAnalyticsPreviewApprove(
    PREVENT_RETURN_WORKFLOW_KEY,
    analyticsMetricKey,
    {
      stage: "inputs",
      title: "Thông tin cần xác nhận",
      body:
        "Không có mặc định Phê duyệt/Từ chối. Nhập lại kho FBS mặc định tắt đến khi kiểm tra thực tế; số lượng còn bán được cần nhập tường minh. Luồng FBT (prevent_return_8b_fbt) chỉ ghi nhận — không thực thi tại đây.",
      inputFields: [
        {
          key: "return_id",
          label: "Mã yêu cầu trả hàng",
          prefillValue: "RT-33190",
          required: true,
          editable: false,
        },
        {
          key: "order_id",
          label: "Mã đơn hàng",
          prefillValue: "ORD-44102",
          required: true,
          editable: false,
        },
        {
          key: "return_reason",
          label: "Lý do trả hàng",
          prefillValue: "Sản phẩm không đúng mô tả",
          required: true,
          editable: false,
        },
        {
          key: "decision_deadline",
          label: "Hạn quyết định",
          prefillValue: "2026-07-20 12:00",
          required: true,
          editable: false,
        },
        {
          key: "rma_state",
          label: "Trạng thái RMA",
          prefillValue: "Đang chờ hàng về kho FBS",
          required: true,
          editable: false,
        },
        {
          key: "risk_evidence",
          label: "Bằng chứng rủi ro (theo quy tắc)",
          prefillValue: "Quy tắc: lần trả đầu — không có điểm ML giả",
          required: false,
          editable: false,
        },
        {
          key: "seller_decision",
          label: "Quyết định của shop (Phê duyệt / Từ chối)",
          prefillValue: "",
          required: true,
          editable: true,
        },
        {
          key: "reject_reason",
          label: "Lý do từ chối (bắt buộc nếu Từ chối)",
          prefillValue: "",
          required: false,
          editable: true,
        },
        {
          key: "review_notes",
          label: "Ghi chú xem xét (khi leo thang)",
          prefillValue: "",
          required: false,
          editable: true,
        },
        {
          key: "restock_enabled",
          label: "Nhập lại kho FBS sau kiểm tra",
          prefillValue: "off",
          required: true,
          editable: true,
        },
        {
          key: "resellable_quantity",
          label: "Số lượng còn bán được (sau kiểm tra)",
          prefillValue: "",
          required: false,
          editable: true,
        },
      ],
    },
  );
}

function getRefundReviewStages(
  analyticsMetricKey: string,
): ReviewStageContent[] {
  return sharedWhyAnalyticsPreviewApprove(
    PREVENT_REFUND_WORKFLOW_KEY,
    analyticsMetricKey,
    {
      stage: "inputs",
      title: "Thông tin cần xác nhận",
      body:
        "Số tiền tính toán chỉ đọc — không ước lượng. Không có mặc định Phê duyệt/Từ chối. Nếu thiếu kết quả tính toán, không phê duyệt. Hoàn tiền không gắn hành động tồn kho (thuộc luồng trả hàng).",
      inputFields: [
        {
          key: "aftersale_id",
          label: "Mã yêu cầu hậu mãi",
          prefillValue: "AS-77201",
          required: true,
          editable: false,
        },
        {
          key: "order_id",
          label: "Mã đơn hàng",
          prefillValue: "ORD-33991",
          required: true,
          editable: false,
        },
        {
          key: "request_reason",
          label: "Lý do yêu cầu",
          prefillValue: "Hoàn tiền một phần sau khi đồng ý giảm giá",
          required: true,
          editable: false,
        },
        {
          key: "calculated_amount",
          label: "Số tiền tính toán (₫)",
          prefillValue: "185000",
          required: true,
          editable: false,
        },
        {
          key: "refund_type",
          label: "Loại hoàn tiền",
          prefillValue: "partial",
          required: true,
          editable: false,
        },
        {
          key: "physical_return_linked",
          label: "Có trả hàng vật lý kèm theo",
          prefillValue: "Không — thuộc luồng trả hàng riêng",
          required: true,
          editable: false,
        },
        {
          key: "decision_deadline",
          label: "Hạn quyết định",
          prefillValue: "2026-07-19 09:00",
          required: true,
          editable: false,
        },
        {
          key: "seller_decision",
          label: "Quyết định của shop (Phê duyệt / Từ chối)",
          prefillValue: "",
          required: true,
          editable: true,
        },
        {
          key: "reject_reason",
          label: "Lý do từ chối (bắt buộc nếu Từ chối)",
          prefillValue: "",
          required: false,
          editable: true,
        },
      ],
    },
  );
}

export function getWorkflowReviewStages(
  workflowKey: string,
  analyticsMetricKey = defaultAnalyticsMetricKey,
): ReviewStageContent[] {
  switch (workflowKey) {
    case CREATE_HERO_PRODUCT_WORKFLOW_KEY:
      return getHeroReviewStages(analyticsMetricKey);
    case PREVENT_CANCELLATION_WORKFLOW_KEY:
      return getCancellationReviewStages(analyticsMetricKey);
    case PREVENT_RETURN_WORKFLOW_KEY:
      return getReturnReviewStages(analyticsMetricKey);
    case PREVENT_REFUND_WORKFLOW_KEY:
      return getRefundReviewStages(analyticsMetricKey);
    default:
      return [];
  }
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
