import type { ReviewStageContent } from "@juli/contracts";

import { recommendationFixtures } from "../../recommendations";
import {
  buildSellerApproveBody,
  buildSellerWhyBody,
  buildSellerPreviewBody,
} from "../../review-seller-copy";

export const REPLENISH_INVENTORY_WORKFLOW_KEY = "replenish_inventory_3"; // gitleaks:allow — documented mock workflow key
export const REPLENISH_INVENTORY_TOOL_NAME = "inventory.replenish";
export const REPLENISH_INVENTORY_FBT_INTAKE_KEY = "replenish_inventory_3b"; // gitleaks:allow — documented FBT intake key

const defaultAnalyticsMetricKey = "cancellation-rate";

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
    warehouse_id: "WH-HCM-01",
    reorder_quantity: "240",
    external_path: "NCC Hóa Mỹ Phẩm",
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
      body: buildSellerWhyBody(replenishFixture),
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
        "SKU và tồn kho hiện tại được đọc từ kho giao hàng đã gán.",
        "Số lượng đặt hàng lại cần shop xác nhận — chưa có mặc định khi chưa kết nối NCC/ERP.",
        "Đường NCC hoặc ERP cần cấu hình thêm vì chưa có tích hợp có thẩm quyền.",
        "Cập nhật tồn kho chỉ chạy sau khi xác nhận số lượng nhận hàng thực tế.",
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
          label: "Tồn kho hiện tại",
          prefillValue: "48 đơn vị — đủ cho khoảng 4 ngày bán",
          required: true,
          editable: false,
        },
        {
          key: "warehouse_id",
          label: "Kho giao hàng",
          prefillValue: "WH-HCM-01 — Kho HCM (từ SKU, chỉ đọc)",
          required: true,
          editable: false,
        },
        {
          key: "reorder_quantity",
          label: "Số lượng đặt hàng lại",
          prefillValue: "Chưa có mặc định — cần shop nhập sau khi xem dữ liệu",
          required: true,
          editable: true,
        },
        {
          key: "external_path",
          label: "Đường bên ngoài (NCC hoặc ERP)",
          prefillValue: "Chưa cấu hình — chọn NCC hoặc ERP khi có tích hợp",
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
      body: buildSellerPreviewBody(replenishFixture, [
        "Juli sẽ theo dõi đặt hàng lại, chờ giao và cập nhật tồn kho sau khi bạn xác nhận số lượng nhận.",
        "Đường NCC/ERP và tạo đơn mua cần cấu hình thêm — Demo ghi nhận bước này.",
      ]),
    },
    {
      stage: "approve",
      title: "Xác nhận phê duyệt",
      body: buildSellerApproveBody([
        "Các bước NCC/ERP và theo dõi giao hàng cần cấu hình thêm trong Demo.",
      ]),
    },
  ];
}
