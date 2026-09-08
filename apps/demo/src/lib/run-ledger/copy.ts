/**
 * Vietnamese seller-facing copy for the run ledger (issue #1318 /
 * W6-A/P-UI-5). Every string here is landed in `dictionary.md` in the same
 * change (ADR-028) -- this module is the runtime constant, the dictionary
 * entry is the governance record; keep them byte-identical.
 */
import type { RunTerminalStateKey } from "./terminal-state";
import type { StatusChipVariant } from "@juli/ui";

export const RUN_LEDGER_SECTION_TITLES = {
  /** `run.awaiting_you` */
  waitingOnYou: "Đang chờ bạn",
  /** `run.status.running` */
  running: "Đang chạy",
  /** `run.section.finished` */
  finished: "Hoàn tất",
} as const;

export const RUN_LEDGER_STATUS_LABELS = {
  /** `run.queued_status` */
  queued: "Trong hàng đợi",
  /** `run.status.running` */
  running: "Đang chạy",
} as const;

export const RUN_LEDGER_BODY_COPY = {
  /** `run.queued_body` */
  queued: "Juli sắp bắt đầu xử lý sản phẩm này.",
  /** `run.running_body_fallback` */
  runningFallback: "Juli đang xử lý sản phẩm này.",
  /** `run.waiting_body` */
  waitingOnYou: "Có một đề xuất đang chờ bạn xác nhận.",
} as const;

export interface RunTerminalStateCopy {
  /** The chip/label text -- distinct per bucket, never a generic "done". */
  label: string;
  chipVariant: StatusChipVariant;
  /** The explanatory sentence on the finished card. */
  body: string;
}

export const RUN_TERMINAL_STATE_COPY: Readonly<
  Record<RunTerminalStateKey, RunTerminalStateCopy>
> = Object.freeze({
  completed: {
    label: "Hoàn tất",
    chipVariant: "success",
    body: "Juli đã hoàn tất và áp dụng thay đổi được phê duyệt.",
  },
  completed_after_decline: {
    label: "Hoàn tất — không đổi",
    chipVariant: "success",
    // `run.declined_note`
    body: "Bạn đã chọn không thay đổi giá",
  },
  cancelled: {
    label: "Đã hủy",
    chipVariant: "neutral",
    body: "Bạn đã hủy luồng này trước khi hoàn tất.",
  },
  expired: {
    label: "Đã hết hạn",
    chipVariant: "warning",
    body: "Đề xuất đã hết hạn trước khi bạn xác nhận.",
  },
  timed_out: {
    label: "Quá thời gian",
    chipVariant: "warning",
    body: "Luồng mất quá nhiều thời gian và Juli đã dừng lại.",
  },
  failed: {
    label: "Thất bại",
    chipVariant: "destructive",
    body: "Đã xảy ra lỗi khi Juli thực hiện; hãy xem lại tại Quyết định.",
  },
  worker_lost: {
    label: "Sự cố",
    chipVariant: "destructive",
    // `run.worker_lost`
    body: "Juli gặp sự cố khi thực hiện",
  },
});

/** Fallback copy for a terminal run whose `stop_reason` this module does
 *  not recognize -- honest ("cannot be shown precisely"), never invented
 *  as one of the seven named buckets. */
export const RUN_TERMINAL_STATE_UNKNOWN_COPY: RunTerminalStateCopy = {
  label: "Đã kết thúc",
  chipVariant: "neutral",
  body: "Luồng đã kết thúc. Vui lòng xem lại tại Quyết định.",
};

/** `run.no_retry` -- every failed/cancelled/expired/timed-out/worker_lost
 *  card carries this instead of any retry-in-place control. */
export const RUN_LEDGER_NO_RETRY_NOTE =
  "Muốn thực hiện thay đổi mới? Hãy quay lại Quyết định để phê duyệt đề xuất mới.";

/** `run.back_to_decisions` -- reuses the exact link text the per-run
 *  not-found recovery state already uses, for one consistent phrase. */
export const RUN_LEDGER_BACK_TO_DECISIONS = "Về Quyết định";

/** `run.loading` */
export const RUN_LEDGER_LOADING = "Đang tải danh sách…";

/** `run.load_error` -- shown on a persistent fetch failure; carries no
 *  manual retry control (polling itself is the retry). */
export const RUN_LEDGER_LOAD_ERROR = "Không thể tải danh sách luồng thực hiện.";

/** `empty.decisions.in_progress_filtered` (already dictionary-governed). */
export const RUN_LEDGER_EMPTY_STATE = "Chưa có quyết định nào đang thực hiện.";

/** `run.expiry`: "Đề xuất còn hiệu lực {time}" */
export function formatRunExpiryCopy(time: string): string {
  return `Đề xuất còn hiệu lực ${time}`;
}
