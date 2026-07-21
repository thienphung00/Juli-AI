import type { ExecutionTimelineStep } from "@juli/contracts";

import {
  PREVENT_RETURN_TOOL_NAME,
  PREVENT_RETURN_WORKFLOW_KEY,
} from "./review";

export { PREVENT_RETURN_TOOL_NAME, PREVENT_RETURN_WORKFLOW_KEY };

export function createPreventReturnTimeline(): ExecutionTimelineStep[] {
  return [
    {
      id: "return-intake",
      stepNumber: 1,
      kind: "wait",
      title: "Tiếp nhận cập nhật trạng thái đảo ngược",
      description: "Webhook #2 ghi nhận yêu cầu trả hàng mới hoặc thay đổi.",
      status: "pending",
    },
    {
      id: "search-returns",
      stepNumber: 2,
      kind: "action",
      title: "Tìm yêu cầu trả hàng",
      description: "Đọc trạng thái yêu cầu chính thức từ Search Returns.",
      status: "pending",
      recoveryText: "Làm mới yêu cầu trả hàng khi dữ liệu bị cũ.",
    },
    {
      id: "get-aftersale-eligibility",
      stepNumber: 3,
      kind: "action",
      title: "Kiểm tra điều kiện hậu mãi",
      description: "Xác nhận cửa sổ và quy tắc mặt hàng còn hiệu lực.",
      status: "pending",
    },
    {
      id: "search-rma",
      stepNumber: 4,
      kind: "action",
      title: "Tìm RMA",
      description:
        "Theo dõi trạng thái trả hàng vật lý trước khi quyết định cuối.",
      status: "pending",
    },
    {
      id: "rma-status-wait",
      stepNumber: 5,
      kind: "wait",
      title: "Chờ cập nhật trạng thái RMA",
      description:
        "Webhook #65 chờ giai đoạn vật lý bắt buộc; thiếu RMA thì chờ rõ ràng.",
      status: "pending",
      recoveryText: "Giữ trạng thái chờ khi thiếu RMA — không bịa hoàn tất.",
    },
    {
      id: "review-aftersales",
      stepNumber: 6,
      kind: "action",
      title: "Xem xét hậu mãi (có điều kiện)",
      description: "Chạy khi trường hợp leo thang/mơ hồ theo quy tắc hiện có.",
      status: "pending",
    },
    {
      id: "get-reject-reasons",
      stepNumber: 7,
      kind: "action",
      title: "Lấy lý do từ chối",
      description: "Tải lý do hợp lệ trước khi từ chối trả hàng.",
      status: "pending",
    },
    {
      id: "seller-decision",
      stepNumber: 8,
      kind: "outcome",
      title: "Cần quyết định của shop",
      description:
        "Shop chọn Phê duyệt hoặc Từ chối; Từ chối bắt buộc có lý do.",
      status: "pending",
      recoveryText: "Thiếu lý do từ chối — chặn gửi và quay lại nhập.",
    },
    {
      id: "approve-return",
      stepNumber: 9,
      kind: "action",
      title: "Phê duyệt trả hàng",
      description: "Gửi phê duyệt (nhánh loại trừ với từ chối).",
      status: "pending",
      recoveryText:
        "Thử lại ghi nhận quyết định theo cách idempotent khi lỗi tạm thời.",
    },
    {
      id: "reject-return",
      stepNumber: 10,
      kind: "action",
      title: "Từ chối trả hàng",
      description: "Gửi từ chối kèm lý do (nhánh loại trừ với phê duyệt).",
      status: "pending",
      recoveryText:
        "Thử lại ghi nhận quyết định theo cách idempotent khi lỗi tạm thời.",
    },
    {
      id: "physical-inspection-wait",
      stepNumber: 11,
      kind: "wait",
      title: "Chờ kiểm tra thực tế",
      description:
        "Với trả hàng FBS đã phê duyệt, thu kết quả còn bán được trước khi nhập kho.",
      status: "pending",
      recoveryText:
        "Giữ kết quả kiểm tra ở trạng thái cần thêm thông tin đến khi có số lượng.",
    },
    {
      id: "update-inventory-fbs",
      stepNumber: 12,
      kind: "action",
      title: "Cập nhật tồn kho FBS (nhập lại kho)",
      description:
        "Chỉ nhập lại số lượng FBS đã kiểm tra còn bán được — không tự động nhập lại. FBT intake (prevent_return_8b_fbt) không có bước seller Update Inventory.",
      status: "pending",
      recoveryText:
        "Giữ kết quả kiểm tra khi nhập kho thất bại; quyết định trả hàng không bị rollback.",
      errorText: "Nhập lại kho thất bại — giữ số lượng đã kiểm tra.",
    },
    {
      id: "get-return-records",
      stepNumber: 13,
      kind: "action",
      title: "Lấy lịch sử trả hàng",
      description: "Đọc bản ghi quyết định/lịch sử sau khi xử lý.",
      status: "pending",
    },
    {
      id: "return-status-wait",
      stepNumber: 14,
      kind: "wait",
      title: "Chờ thay đổi trạng thái trả hàng",
      description:
        "Webhook #12 xác nhận trạng thái cuối; timeout thì làm mới, không bịa hoàn tất.",
      status: "pending",
      recoveryText:
        "Làm mới bản ghi trả hàng sau timeout — không tuyên bố hoàn tất sớm.",
    },
    {
      id: "return-outcome",
      stepNumber: 15,
      kind: "outcome",
      title: "Đã trả / từ chối / nhập lại kho / thất bại",
      description:
        "Tách quyết định trả hàng khỏi đối soát tồn kho. Thành công quyết định + lỗi nhập kho là kết quả một phần, không rollback quyết định.",
      status: "pending",
      recoveryText:
        "Giữ kết quả kiểm tra và hiển thị lỗi nhập kho riêng nếu có.",
    },
  ];
}
