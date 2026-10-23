import { DemoDecisionApproveError } from "../decision-approve-error";

/** P66 (D13): the reviewer caps' codes → what was used up. */
const CAP_SUBJECT: Readonly<Record<string, string>> = {
  create_product_daily_cap: "sản phẩm",
  create_promotion_daily_cap: "khuyến mãi",
};

/** `HH:MM dd/mm` in Vietnam time, or null. */
function vnClock(iso: string | null): string | null {
  if (!iso) return null;
  const time = Date.parse(iso);
  if (!Number.isFinite(time)) return null;
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Ho_Chi_Minh",
      hour: "2-digit",
      minute: "2-digit",
      day: "2-digit",
      month: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(new Date(time))
      .map((part) => [part.type, part.value]),
  );
  return `${parts.hour}:${parts.minute} ${parts.day}/${parts.month}`;
}

/**
 * dictionary.md `error.approve.*` — one honest sentence per refusal the approve route
 * distinguishes. P66 (D13): the reviewer's daily caps say what was used up and when it
 * frees up; 403 / 422 / 5xx each get their own sentence — never nothing.
 */
export function describeApproveError(error: unknown): string {
  if (error instanceof DemoDecisionApproveError) {
    const code = error.detail?.code ?? null;
    if (error.status === 429 && code && CAP_SUBJECT[code]) {
      const cap = error.detail?.cap ?? 3;
      const at = vnClock(error.detail?.retryAt ?? null);
      return `Đã tạo ${cap} ${CAP_SUBJECT[code]} trên TikTok trong 24 giờ qua (giới hạn của tài khoản đánh giá)${
        at ? `; thử lại lúc ${at}` : "; vui lòng thử lại sau"
      }.`;
    }
    if (error.status === 429) {
      return "Bạn đã duyệt quá nhiều thẻ trong thời gian ngắn. Vui lòng thử lại sau ít phút.";
    }
    if (error.status === 401) {
      return "Phiên đăng nhập của bạn không còn hiệu lực. Vui lòng đăng nhập với Google lại, rồi duyệt.";
    }
    if (error.status === 403) {
      return "Tài khoản này chỉ được thao tác trên shop sandbox của Juli. Juli không ghi gì lên shop này.";
    }
    if (error.status === 404) {
      return "Đề xuất này không còn tồn tại hoặc không thuộc shop bạn đang thao tác.";
    }
    if (error.status === 409) {
      return "Đề xuất này đã được xử lý, hoặc sản phẩm đang có luồng khác chạy. Hãy kiểm tra tab Đang thực hiện.";
    }
    if (error.status === 422) {
      const message = error.detail?.message ?? null;
      return message && /[À-ỹ]/.test(message)
        ? message
        : "Đề xuất này không qua được quy tắc của shop. Hãy kiểm tra Quy tắc của bạn rồi duyệt lại.";
    }
    if (error.status >= 500) {
      return "Máy chủ Juli đang gặp sự cố nên chưa duyệt được. Vui lòng thử lại sau ít phút.";
    }
    return "Chưa thể duyệt đề xuất này lúc này. Vui lòng thử lại.";
  }
  return "Không thể kết nối. Vui lòng kiểm tra mạng và thử lại.";
}
