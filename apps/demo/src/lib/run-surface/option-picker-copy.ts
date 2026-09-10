/**
 * Vietnamese seller-facing copy for the Đề xuất option picker (issue #1317,
 * PUI-DESIGN.md §3/§7). Landed in `dictionary.md` in the same change
 * (ADR-028) -- this module is the runtime constant, the dictionary entry is
 * the governance record; keep them byte-identical.
 */
import type { ConfirmationErrorCode } from "./confirmation-decision";

/** `run.confirm_option` */
export const OPTION_PICKER_CONFIRM_LABEL = "Xác nhận phương án này";
/** `run.decline_option` */
export const OPTION_PICKER_DECLINE_LABEL = "Không thực hiện";
/** `run.decline_outcome` */
export const OPTION_PICKER_DECLINE_OUTCOME =
  "Juli sẽ hoàn tất mà không thay đổi gì, và phần phân tích được giữ lại.";
/** `run.option_picker.expired` */
export const OPTION_PICKER_EXPIRED_COPY = "Đề xuất đã hết hiệu lực.";
/** `run.option_picker.submitting` */
export const OPTION_PICKER_SUBMITTING_COPY = "Đang gửi lựa chọn của bạn…";
/** `run.no_retry` -- reused verbatim (ADR-084 decision 6: no retry-in-place
 *  control). Explains the expired/rejected state's dead end honestly rather
 *  than offering a control that cannot exist. */
export const OPTION_PICKER_NO_RETRY_COPY =
  "Muốn thực hiện thay đổi mới? Hãy quay lại Quyết định để phê duyệt đề xuất mới.";

/** `run.option_picker.heading`, `{count}` substituted -- never a literal. */
export function formatOptionPickerHeading(count: number): string {
  return `Juli đề xuất ${count} phương án:`;
}

/**
 * `run.confirmation_rejected.*` -- one distinct, honest sentence per server
 * condition (issue #1317's AC: "a rejected confirmation ... renders the
 * server's distinct condition honestly rather than a generic failure").
 * An `error_code` this table has no entry for still renders SOMETHING
 * truthful (the generic fallback), never silence or a spinner.
 */
const CONFIRMATION_REJECTED_COPY: Readonly<Record<string, string>> = Object.freeze({
  confirmation_already_decided: "Đề xuất này đã được quyết định trước đó.",
  run_not_awaiting_confirmation: "Luồng thực hiện này không còn chờ xác nhận.",
  params_sha_mismatch:
    "Đề xuất đã thay đổi kể từ khi bạn xem; hãy quay lại Quyết định để xem đề xuất mới nhất.",
});

/** `run.confirmation_rejected.generic` */
const CONFIRMATION_REJECTED_GENERIC_COPY = "Không thể xác nhận lựa chọn này.";

export function describeConfirmationRejection(errorCode: ConfirmationErrorCode | null): string {
  if (errorCode && CONFIRMATION_REJECTED_COPY[errorCode]) {
    return CONFIRMATION_REJECTED_COPY[errorCode];
  }
  return CONFIRMATION_REJECTED_GENERIC_COPY;
}
