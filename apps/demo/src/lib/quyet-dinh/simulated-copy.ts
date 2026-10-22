/**
 * Fast track P61-B (D71.2): a run whose writes went to Juli's test shop rather than the
 * seller's shop (`WorkflowRunListItem.simulated`, card status `simulated`). The seller is
 * never told such a run changed their shop, and it has no Đo lường.
 */

export const SIMULATED_RUN_LABEL = "Đã chạy thử";

export const SIMULATED_DONE_TITLE = "Đã chạy thử · shop của bạn chưa thay đổi";

export const SIMULATED_DONE_TEXT =
  "Lượt này chỉ chạy thử, chưa ghi lên TikTok Shop của bạn: sản phẩm giữ nguyên, nên Juli không đo kết quả.";

/**
 * P64 (D73.4): for the partner account pinned to Juli's live TikTok sandbox shop the
 * sandbox shop IS the shop, so a run that wrote there really changed it on TikTok —
 * never "chạy thử". The seller's own shop keeps {@link SIMULATED_RUN_LABEL}.
 */
export const SANDBOX_WRITTEN_LABEL = "Đã ghi lên TikTok";
