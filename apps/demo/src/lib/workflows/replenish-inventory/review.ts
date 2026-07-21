import type { ReviewStageContent } from "@juli/contracts";

import { recommendationFixtures } from "../../recommendations";

export const REPLENISH_INVENTORY_WORKFLOW_KEY = "replenish_inventory_3"; // gitleaks:allow — documented mock workflow key
export const REPLENISH_INVENTORY_TOOL_NAME = "inventory.replenish";
export const REPLENISH_INVENTORY_FBT_INTAKE_KEY = "replenish_inventory_3b"; // gitleaks:allow — documented FBT intake key

const defaultAnalyticsMetricKey = "stockout-rate";

const replenishFixtureEntry = recommendationFixtures.find(
  (fixture) => fixture.workflowKey === REPLENISH_INVENTORY_WORKFLOW_KEY,
);

if (!replenishFixtureEntry) {
  throw new Error("Missing replenish_inventory_3 recommendation fixture");
}

const replenishFixture = replenishFixtureEntry;

export function buildReplenishInventoryReviewInputDefaults(): Record<
  string,
  string
> {
  return {
    sku_id: "SKU-SPF50-001",
    current_stock: "48",
    warehouse_id: "WH-FBS-HCM-01",
    reorder_quantity: "",
    external_path: "",
    received_quantity: "",
  };
}

export function getReplenishInventoryReviewStages(
  analyticsMetricKey = defaultAnalyticsMetricKey,
): ReviewStageContent[] {
  const analyticsMetricHref = `/analytics/${analyticsMetricKey}`;

  return [
    {
      stage: "why",
      title: "Vì sao đề xuất này",
      body: [
        replenishFixture.reasoning,
        replenishFixture.signal,
        replenishFixture.evidence,
        replenishFixture.risks,
      ].join("\n\n"),
    },
    {
      stage: "analytics",
      title: "Bằng chứng từ Phân tích",
      body:
        "Xem KPI Tỷ lệ hết hàng trên Phân tích để hiểu thêm bối cảnh trước khi phê duyệt. Demo không nhân bản báo cáo tại đây.",
      analyticsMetricKey,
      analyticsMetricHref,
    },
    {
      stage: "inputs",
      title: "Thông tin cần xác nhận",
      body: [
        "SKU và tồn kho hiện tại được đọc từ kho FBS đã gán.",
        "Số lượng đặt hàng lại cần shop xác nhận — ROP/EOQ chưa có mặc định khi chưa kết nối.",
        "Đường NCC hoặc ERP được ghi nhãn Unresolved vì chưa có hợp đồng tích hợp có thẩm quyền.",
        "Cập nhật tồn kho FBS chỉ chạy sau khi xác nhận số lượng nhận hàng thực tế.",
      ].join("\n\n"),
      inputFields: [
        {
          key: "sku_id",
          label: "SKU",
          prefillValue: "SKU-SPF50-001 — Kem chống nắng SPF50",
          required: true,
          editable: false,
        },
        {
          key: "current_stock",
          label: "Tồn kho hiện tại (FBS)",
          prefillValue: "48 đơn vị — đủ cho khoảng 4 ngày bán",
          required: true,
          editable: false,
        },
        {
          key: "warehouse_id",
          label: "Kho FBS",
          prefillValue: "WH-FBS-HCM-01 — Kho HCM (từ SKU, chỉ đọc)",
          required: true,
          editable: false,
        },
        {
          key: "reorder_quantity",
          label: "Số lượng đặt hàng lại",
          prefillValue: "Chưa có mặc định — ROP/EOQ chưa được kết nối",
          required: true,
          editable: true,
        },
        {
          key: "external_path",
          label: "Đường bên ngoài (NCC hoặc ERP)",
          prefillValue:
            "Unresolved — chọn NCC hoặc ERP khi có hợp đồng tích hợp",
          required: true,
          editable: true,
        },
        {
          key: "received_quantity",
          label: "Số lượng nhận hàng thực tế (sau giao)",
          prefillValue: "",
          required: false,
          editable: true,
        },
      ],
    },
    {
      stage: "preview",
      title: "Xem trước trước khi phê duyệt",
      body: [
        `Công cụ: ${replenishFixture.toolName}`,
        `Khả năng: ${replenishFixture.capabilityLabel}`,
        `Điều kiện: ${replenishFixture.eligibility}`,
        replenishFixture.knownLimits,
        `Luồng FBS: tra cứu tồn kho → xác nhận điều kiện → đường NCC/ERP (Unresolved) → tạo đơn mua/Purchase Request (Unresolved) → chờ giao → xác nhận nhận hàng → cập nhật tồn kho → đối soát webhook #27/#68.`,
        `FBT intake \`${REPLENISH_INVENTORY_FBT_INTAKE_KEY}\`: Unresolved/Unfilled — không hiển thị như luồng có thể thực thi cho đến khi có hợp đồng tạo Inbound Shipment.`,
      ].join("\n\n"),
    },
    {
      stage: "approve",
      title: "Xác nhận phê duyệt",
      body: [
        "Phê duyệt sẽ ghi nhận workflow_key và tool_name, sau đó mở luồng Đang thực hiện cho nhánh FBS.",
        "Các bước NCC/ERP, tạo Purchase Order/Purchase Request, và theo dõi giao hàng NCC vẫn được ghi nhãn Unresolved — demo không gọi API bên thứ ba hay TikTok thật.",
        "Không cam kết luồng FBT cho đến khi hợp đồng replenish_inventory_3b được xác định.",
      ].join("\n\n"),
    },
  ];
}
