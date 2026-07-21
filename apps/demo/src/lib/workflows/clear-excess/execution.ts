import type { ExecutionTimelineStep } from "@juli/contracts";

export const CLEAR_EXCESS_WORKFLOW_KEY = "clear_excess_4";
export const CLEAR_EXCESS_TOOL_NAME = "inventory.clear_excess";

export function createClearExcessTimeline(): ExecutionTimelineStep[] {
  return [
    {
      id: "inventory-search",
      stepNumber: 1,
      kind: "action",
      title: "Tra cứu tồn kho",
      description:
        "Xác nhận số lượng và SKU tồn lâu ngày trước khi lập kế hoạch xả hàng FBS.",
      status: "pending",
      recoveryText:
        "Tồn kho đã thay đổi — chạy lại tra cứu trước khi tiếp tục giảm giá hoặc tạo khuyến mãi.",
    },
    {
      id: "get-activity",
      stepNumber: 2,
      kind: "action",
      title: "Lấy chương trình khuyến mãi",
      description:
        "Đọc activity_id đã biết khi cần cập nhật hoặc tránh trùng lặp khuyến mãi.",
      status: "pending",
    },
    {
      id: "clearance-eligibility-outcome",
      stepNumber: 3,
      kind: "outcome",
      title: "Kết quả điều kiện xả hàng",
      description:
        "Hiển thị SKU, giá, ràng buộc khuyến mãi và trạng thái kiểm tra Flash Sale thật — Demo không giả lập “đủ điều kiện”.",
      status: "pending",
      recoveryText:
        "Flash Sale chưa đủ điều kiện — quay lại chọn giảm giá cơ sở hoặc loại khuyến mãi khác với xác nhận của shop.",
    },
    {
      id: "update-price",
      stepNumber: 4,
      kind: "action",
      title: "Cập nhật giá",
      description:
        "Áp dụng markdown cơ sở đã được phê duyệt trước khi tạo hoặc bỏ qua khuyến mãi.",
      status: "pending",
      recoveryText:
        "TikTok từ chối cập nhật giá — quay lại bước nhập liệu để chỉnh markdown hoặc SKU.",
    },
    {
      id: "create-activity",
      stepNumber: 5,
      kind: "action",
      title: "Tạo chương trình khuyến mãi",
      description:
        "Chỉ chạy khi loại khuyến mãi đã chọn và điều kiện thật cho phép — bỏ qua nếu chỉ giảm giá cơ sở.",
      status: "pending",
      recoveryText:
        "Không thể tạo khuyến mãi — thử lại sau khi xác nhận điều kiện hoặc chuyển sang nhánh chỉ giảm giá.",
    },
    {
      id: "update-activity-product",
      stepNumber: 6,
      kind: "action",
      title: "Gắn sản phẩm vào khuyến mãi",
      description:
        "Đính kèm SKU và giá xả hàng đã duyệt vào activity_id đã tạo.",
      status: "pending",
      recoveryText:
        "Một phần SKU không gắn được — giữ activity hiện tại và thử lại SKU bị lỗi.",
    },
    {
      id: "activity-status-wait",
      stepNumber: 7,
      kind: "wait",
      title: "Chờ trạng thái khuyến mãi",
      description:
        "Lắng nghe webhook thay đổi trạng thái khuyến mãi (#39) cho đến khi live hoặc thất bại; không hiển thị ETA giả.",
      status: "pending",
      recoveryText:
        "Khuyến mãi thất bại — giữ giá đã cập nhật, không tự hoàn tác; shop chọn thử lại hoặc chỉ giảm giá.",
    },
    {
      id: "clearance-active-outcome",
      stepNumber: 8,
      kind: "outcome",
      title: "Khuyến mãi xả hàng đang chạy",
      description:
        "Hiển thị cửa sổ khuyến mãi đang hoạt động và tồn kho quan sát được trên kho FBS.",
      status: "pending",
    },
    {
      id: "update-inventory-zero",
      stepNumber: 9,
      kind: "action",
      title: "Cập nhật tồn kho sàn FBS về 0",
      description:
        "Chỉ chạy sau khi mục tiêu xả hàng hoặc kiểm đếm thực tế được xác nhận — bước không thể hoàn tác trên kho FBS.",
      status: "pending",
      recoveryText:
        "Cần xác nhận số lượng thực tế trước khi ghi tồn về 0 — không tự chạy chỉ vì hết thời gian khuyến mãi.",
    },
    {
      id: "inventory-reconciliation-wait",
      stepNumber: 10,
      kind: "wait",
      title: "Chờ đối soát tồn kho",
      description:
        "Lắng nghe webhook thay đổi trạng thái tồn kho (#27) và thay đổi số lượng (#68) cho đến khi khớp số liệu quan sát.",
      status: "pending",
      recoveryText:
        "Hết thời gian chờ đối soát — hiển thị tồn kho quan sát hiện tại và cho phép làm mới thủ công, không báo thành công giả.",
    },
    {
      id: "deactivate-activity",
      stepNumber: 11,
      kind: "action",
      title: "Kết thúc chương trình khuyến mãi",
      description:
        "Đóng activity_id đã biết khi xả hàng xong hoặc hết hạn.",
      status: "pending",
      recoveryText:
        "Không thể kết thúc khuyến mãi — thử lại và giữ trạng thái đang hoạt động cho đến khi thành công.",
      errorText: "Kết thúc khuyến mãi thất bại — thử lại.",
    },
    {
      id: "cleared-outcome",
      stepNumber: 12,
      kind: "outcome",
      title: "Đã xả hàng / một phần / thất bại",
      description:
        "Hiển thị tồn kho cuối cùng và trạng thái khuyến mãi trên kho FBS; luồng FBT không được coi là đã thực thi.",
      status: "pending",
      recoveryText:
        "Một phần SKU chưa xả hết — xem lại kế hoạch giảm giá hoặc khuyến mãi trước khi thử lại.",
    },
  ];
}
