import { describe, expect, it, vi } from "vitest";

import { DemoDecisionApproveError, approveRefusalDetail } from "../decision-approve-error";
import { describeApproveError } from "../quyet-dinh/approve-errors";
import { approveDemoDecision } from "../recommendations-api-client";

/** P66 (D13): every approve refusal has Vietnamese copy on the card. */
describe("describeApproveError", () => {
  it("names the used-up reviewer cap and when it frees up (Vietnam time)", () => {
    const error = new DemoDecisionApproveError(
      429,
      approveRefusalDetail({
        detail: { code: "create_product_daily_cap", cap: 3, retry_at: "2026-10-23T05:43:00Z", retry_after_seconds: 60 },
      }),
    );
    expect(describeApproveError(error)).toBe(
      "Đã tạo 3 sản phẩm trên TikTok trong 24 giờ qua (giới hạn của tài khoản đánh giá); thử lại lúc 12:43 23/10.",
    );
    const promo = new DemoDecisionApproveError(429, approveRefusalDetail({ detail: { code: "create_promotion_daily_cap", cap: 3 } }));
    expect(describeApproveError(promo)).toBe(
      "Đã tạo 3 khuyến mãi trên TikTok trong 24 giờ qua (giới hạn của tài khoản đánh giá); vui lòng thử lại sau.",
    );
  });

  it.each([
    [429, "Too many approve requests", "Bạn đã duyệt quá nhiều thẻ trong thời gian ngắn. Vui lòng thử lại sau ít phút."],
    [403, { code: "sandbox_only" }, "Tài khoản này chỉ được thao tác trên shop sandbox của Juli. Juli không ghi gì lên shop này."],
    [409, "Decision is not active", "Đề xuất này đã được xử lý, hoặc sản phẩm đang có luồng khác chạy. Hãy kiểm tra tab Đang thực hiện."],
    [422, { code: "rule_violation", message: "Mức giảm phải từ 5% đến 12%" }, "Mức giảm phải từ 5% đến 12%"],
    [422, { code: "rule_violation", message: "bad" }, "Đề xuất này không qua được quy tắc của shop. Hãy kiểm tra Quy tắc của bạn rồi duyệt lại."],
    [503, null, "Máy chủ Juli đang gặp sự cố nên chưa duyệt được. Vui lòng thử lại sau ít phút."],
  ])("status %s → its own sentence", (status, detail, text) => {
    const error = new DemoDecisionApproveError(status, approveRefusalDetail(detail === null ? null : { detail }));
    expect(describeApproveError(error)).toBe(text);
  });
});

describe("approveDemoDecision", () => {
  it("keeps the refusal body's detail on the error", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: { code: "create_promotion_daily_cap", cap: 3, retry_at: "2026-10-23T05:43:00Z" } }), {
          status: 429,
          headers: { "Content-Type": "application/json" },
        }),
    ) as unknown as typeof fetch;
    const failure = await approveDemoDecision("card-1", { token: "t", shopId: "s", fetchImpl }).catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(DemoDecisionApproveError);
    expect((failure as DemoDecisionApproveError).detail).toEqual({
      code: "create_promotion_daily_cap",
      cap: 3,
      retryAt: "2026-10-23T05:43:00Z",
      message: null,
    });
  });
});
