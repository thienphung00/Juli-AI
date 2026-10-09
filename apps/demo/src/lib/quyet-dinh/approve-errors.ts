import { DemoDecisionApproveError } from "../decision-approve-error";

/** dictionary.md `error.approve.*` — one honest sentence per status the approve route distinguishes. */
export function describeApproveError(error: unknown): string {
  if (error instanceof DemoDecisionApproveError) {
    if (error.status === 401) {
      return "Phiên đăng nhập của bạn không còn hiệu lực. Vui lòng đăng nhập với Google lại, rồi phê duyệt.";
    }
    if (error.status === 404) {
      return "Đề xuất này không còn tồn tại hoặc không thuộc shop bạn đang thao tác.";
    }
    if (error.status === 409) {
      return "Đề xuất này đã được xử lý, hoặc sản phẩm đang có luồng khác chạy. Hãy kiểm tra tab Đang thực hiện.";
    }
    return `Chưa thể phê duyệt đề xuất này lúc này (lỗi ${error.status}). Vui lòng thử lại.`;
  }
  return "Không thể kết nối. Vui lòng kiểm tra mạng và thử lại.";
}
