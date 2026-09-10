/**
 * Vietnamese seller-facing copy for the staged run view (issue #1316,
 * PUI-DESIGN.md §2/§8). Every string here is landed in `dictionary.md` in
 * the same change (ADR-028) -- this module is the runtime constant, the
 * dictionary entry is the governance record; keep them byte-identical.
 */
import type { RunStageId } from "./reduce-run-view";

export const RUN_STAGE_NAV_COPY = {
  /** `run.stage.back` */
  back: "Xem lại",
  /** `run.stage.continue` */
  continueToLiveEdge: "Tiếp",
} as const;

/** Accessible (screen-reader/aria) status suffix per stepper node status --
 *  never rendered as the only cue (color/position carry it visually too),
 *  but always present in the accessible name. */
export const RUN_STAGE_STATUS_COPY = {
  /** `run.stage.status.frozen` */
  frozen: "Đã hoàn tất",
  /** `run.stage.status.active` */
  active: "Đang diễn ra",
  /** `run.stage.status.locked` */
  locked: "Chưa mở khoá",
} as const;

/** `run.product_binding.label` */
export const RUN_PRODUCT_BINDING_LABEL = "Sản phẩm đang xử lý";

/** `run.reconnecting` */
export const RUN_STREAM_RECONNECTING_COPY = "Đang kết nối lại";

/** Fallback narration for the Phân tích stage before the agent has said
 *  anything yet -- reuses the run ledger's already-reviewed sentence
 *  (`run.running_body_fallback`) rather than introducing a second,
 *  unreviewed "Juli is working" string. */
export const RUN_STAGE_ANALYZING_FALLBACK = "Juli đang xử lý sản phẩm này.";

/**
 * Seller-facing action labels for known tool calls -- NEVER the raw
 * `tool_name` string. `tool_name` is an internal implementation detail
 * (`SELLER_COPY_BANNED_PATTERNS`'s own `tool_name`/`workflow_key` entries
 * exist for exactly this reason), so the stage canvas looks up a label here
 * instead of interpolating the event's `payload.tool_name` directly. An
 * unrecognized tool name (a future addition this table has not caught up
 * with yet) falls back to a generic, still-honest label rather than
 * leaking the raw identifier.
 */
const RUN_TOOL_ACTION_LABELS: Readonly<Record<string, string>> = Object.freeze({
  get_product_information: "Xem thông tin sản phẩm",
  get_seo_keywords: "Tìm từ khoá SEO",
  update_product_listing: "Cập nhật thông tin sản phẩm",
  upload_staged_image: "Tải ảnh sản phẩm",
});

const RUN_TOOL_ACTION_FALLBACK = "Đang xử lý";

export function describeToolAction(toolName: string): string {
  for (const [prefix, label] of Object.entries(RUN_TOOL_ACTION_LABELS)) {
    if (toolName === prefix || toolName.startsWith(prefix)) return label;
  }
  return RUN_TOOL_ACTION_FALLBACK;
}

/** Per-stage empty-state copy shown when a stage's own event-driven content
 *  is empty -- distinct per stage so the seller reads "nothing found here
 *  yet," never a generic blank. */
export const RUN_STAGE_EMPTY_COPY: Readonly<Record<RunStageId, string>> = Object.freeze({
  "phan-tich": RUN_STAGE_ANALYZING_FALLBACK,
  "thong-tin-san-pham": "Chưa có thông tin sản phẩm.",
  seo: "Không có bước phân tích từ khoá SEO trong luồng này.",
  "de-xuat": "Chưa có đề xuất nào đang chờ.",
  "cap-nhat": "Chưa có thay đổi nào được thực hiện.",
  "hoan-tat": "Đang chờ kết quả cuối cùng.",
});
