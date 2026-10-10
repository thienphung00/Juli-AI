/**
 * The signed-out / no-shop "Phân tích video" (P15): one canned analysis per
 * kind for the sample shop's content (MN-015 video, SM-012 LIVE). Bundled,
 * never fetched — no module reachable from here performs a request. The
 * upload control is disabled in the sample.
 */

import type { AnalysisTarget, ContentAnalysis, ContentAnalysisClients } from "./types";

const VIDEO: ContentAnalysis = {
  id: "sample-analysis-video",
  kind: "video",
  content_ref: null,
  tiktok_product_id: null,
  run_id: null,
  file_name: "mat-na-dat-set.mp4",
  status: "done",
  status_label: "Đã phân tích",
  upload: { received_bytes: 48_000_000, size_bytes: 48_000_000 },
  duration_s: 32,
  error: null,
  result: {
    kind: "video",
    analysed_s: 32,
    hook: { verdict: "weak", label: "Yếu", from_s: 0, to_s: 3, reason: "Mở bằng lời chào, chưa nêu vấn đề da khô và chưa có chữ trên màn hình." },
    product_first_s: 6,
    product_line: "Sản phẩm xuất hiện lần đầu ở giây 6,0",
    cta: { present: true, at_s: 29, text: "Bấm giỏ hàng vàng để lấy giá hôm nay nha", line: "Có lời kêu gọi mua ở giây 29,0" },
    pacing: { cuts: 4, cuts_per_10s: 1.3, line: "4 lần cắt · 1,3 lần / 10 giây" },
    issues: [
      { code: "product_late", text: "Sản phẩm xuất hiện lần đầu ở giây 6,0, muộn hơn 3 giây đầu." },
      { code: "hook_weak", text: "3 giây đầu là lời chào, người xem chưa biết video nói về gì." },
      { code: "cta_late", text: "Lời kêu gọi mua chỉ có ở 3 giây cuối." },
    ],
    suggestions: [
      "Mở bằng câu “Da khô bong tróc sau 1 tuần?” kèm chữ lớn trên màn hình.",
      "Cầm hũ mặt nạ trước camera ngay giây đầu.",
      "Nhắc giỏ hàng vàng một lần ở giữa video, không chỉ ở cuối.",
    ],
    windows: [],
  },
  cost_usd: 0.004,
  file_deleted: true,
  created_at: "2026-10-09T03:00:00Z",
  completed_at: "2026-10-09T03:01:10Z",
};

const LIVE: ContentAnalysis = {
  ...VIDEO,
  id: "sample-analysis-live",
  kind: "live",
  file_name: "live-0410.mp4",
  duration_s: 5400,
  result: {
    kind: "live",
    analysed_s: 840,
    hook: { verdict: "ok", label: "Tạm được", from_s: 1260, to_s: 1290, reason: "Có giới thiệu giá khi ghim, nhưng chưa trình diễn sản phẩm." },
    product_first_s: 1262,
    product_line: "Sản phẩm xuất hiện lần đầu ở 21:02",
    cta: { present: true, at_s: 1395, text: "Chốt đơn ở giỏ số 1 nha cả nhà", line: "Có lời kêu gọi mua ở 23:15" },
    pacing: { cuts: 2, cuts_per_10s: 0, line: "2 lần cắt · 0 lần / 10 giây" },
    issues: [
      { code: "other", text: "Sản phẩm chỉ được nhắc 2 lần trong 90 phút." },
      { code: "hook_weak", text: "Khi ghim sản phẩm, người dẫn chưa nói lợi ích chính." },
    ],
    suggestions: ["Ghim SM-012 khi nói giá và trình diễn trong 30 giây đầu.", "Nhắc lại ưu đãi sau mỗi 10 phút."],
    windows: [
      { from_s: 1140, to_s: 1560, mention_s: 1260, source: "asr_mention" },
      { from_s: 3900, to_s: 4320, mention_s: 4020, source: "asr_mention" },
    ],
  },
};

export const SAMPLE_ANALYSES: Readonly<Record<"video" | "live", ContentAnalysis>> = { video: VIDEO, live: LIVE };

export function createSampleAnalysisClients(): ContentAnalysisClients {
  return {
    sample: true,
    list: async (target: AnalysisTarget) => [SAMPLE_ANALYSES[target.kind]],
    get: async (id: string) => (id === LIVE.id ? LIVE : VIDEO),
    upload: async () => {
      throw new Error("Bản minh họa: đăng nhập và kết nối shop để tải video lên.");
    },
  };
}
