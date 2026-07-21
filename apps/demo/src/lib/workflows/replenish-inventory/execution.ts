import type { ExecutionTimelineStep } from "@juli/contracts";

export const REPLENISH_INVENTORY_WORKFLOW_KEY = "replenish_inventory_3"; // gitleaks:allow — documented mock workflow key
export const REPLENISH_INVENTORY_TOOL_NAME = "inventory.replenish";
export const REPLENISH_INVENTORY_FBT_INTAKE_KEY = "replenish_inventory_3b"; // gitleaks:allow — documented FBT intake key

export function createReplenishInventoryTimeline(): ExecutionTimelineStep[] {
  return [
    {
      id: "inventory-search",
      stepNumber: 1,
      kind: "action",
      title: "Tra cứu tồn kho",
      description:
        "Tải số lượng SKU/kho FBS hiện tại qua Inventory Search trước khi xác nhận điều kiện nhập hàng.",
      status: "pending",
      recoveryText:
        "Làm mới tra cứu khi dữ liệu tồn kho có thể đã cũ trước khi tiếp tục.",
    },
    {
      id: "eligibility-outcome",
      stepNumber: 2,
      kind: "outcome",
      title: "Kết quả điều kiện nhập hàng",
      description:
        "Tiếp tục khi SKU đã xác thực, kho FBS hợp lệ, và số lượng đặt hàng lại được duyệt; nếu thiếu thì chuyển sang cần thêm thông tin.",
      status: "pending",
      recoveryText:
        "Bổ sung số lượng đặt hàng lại hoặc điều kiện còn thiếu trước khi tiếp tục.",
    },
    {
      id: "external-path-input",
      stepNumber: 3,
      kind: "outcome",
      title: "Cần chọn đường bên ngoài",
      description:
        "Shop chọn NCC hoặc ERP. Unresolved — chưa có hợp đồng tích hợp NCC/ERP có thẩm quyền; không tự suy diễn executor.",
      status: "pending",
      recoveryText:
        "Chọn NCC hoặc ERP khi hợp đồng sẵn sàng; nếu không có tích hợp thì giữ trạng thái Unresolved.",
    },
    {
      id: "create-po-unresolved",
      stepNumber: 4,
      kind: "action",
      title: "Unresolved — Tạo đơn mua / Purchase Request",
      description:
        "Unresolved — chưa có hợp đồng API cho Create Purchase Order hoặc Purchase Request; demo không mô phỏng hành vi gửi đơn.",
      status: "pending",
    },
    {
      id: "supplier-delivery-wait",
      stepNumber: 5,
      kind: "wait",
      title: "Chờ giao hàng NCC",
      description:
        "Theo dõi giao hàng bên ngoài vẫn Unresolved; chỉ cho phép xác nhận nhận hàng do shop khi chính sách sản phẩm cho phép.",
      status: "pending",
      recoveryText:
        "Xác nhận nhận hàng thủ công khi hàng đến; không hiển thị ETA giả khi chưa có hợp đồng theo dõi.",
    },
    {
      id: "receipt-confirmed-outcome",
      stepNumber: 6,
      kind: "outcome",
      title: "Đã xác nhận nhận hàng nhập kho",
      description:
        "Hiển thị số lượng nhận thực tế và chênh lệch so với đơn trước khi ghi tồn kho.",
      status: "pending",
      recoveryText:
        "Điều chỉnh số lượng nhận hàng khi có chênh lệch trước khi cập nhật tồn kho.",
    },
    {
      id: "update-inventory",
      stepNumber: 7,
      kind: "action",
      title: "Cập nhật tồn kho FBS",
      description:
        "Ghi số lượng đã xác nhận vào kho FBS của seller qua Update Inventory.",
      status: "pending",
      recoveryText:
        "Giữ bằng chứng nhận hàng và thử lại idempotent khi cập nhật thất bại.",
      errorText: "Cập nhật tồn kho thất bại — thử lại sau khi giữ bằng chứng nhận hàng.",
    },
    {
      id: "inventory-reconciliation-wait",
      stepNumber: 8,
      kind: "wait",
      title: "Chờ đối soát tồn kho",
      description:
        "Lắng nghe Inventory status change (#27) và Inventory changed (#68); không hiển thị thành công trước khi webhook tới hoặc shop làm mới thủ công.",
      status: "pending",
      recoveryText:
        "Hiển thị số lượng quan sát cuối cùng và làm mới thủ công khi webhook quá hạn.",
    },
    {
      id: "reconciled-outcome",
      stepNumber: 9,
      kind: "outcome",
      title: "Tồn kho bán được đã đối soát / chênh lệch",
      description:
        "Hiển thị số lượng quan sát cuối cùng sau đối soát; nêu chênh lệch nếu có so với số lượng ghi.",
      status: "pending",
      recoveryText:
        "Quay lại xác nhận nhận hàng hoặc cập nhật tồn kho khi chênh lệch chưa được giải quyết.",
    },
  ];
}
