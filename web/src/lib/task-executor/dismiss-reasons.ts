export const TASK_DISMISS_REASONS = [
  "false_positive",
  "already_handled",
  "not_relevant",
  "other",
] as const;

export type TaskDismissReason = (typeof TASK_DISMISS_REASONS)[number];

export const TASK_DISMISS_REASON_LABELS: Record<TaskDismissReason, string> = {
  false_positive: "Báo động sai — không phải vấn đề thật",
  already_handled: "Đã xử lý rồi",
  not_relevant: "Không liên quan shop của tôi",
  other: "Lý do khác",
};

export function isTaskDismissReason(value: string): value is TaskDismissReason {
  return (TASK_DISMISS_REASONS as readonly string[]).includes(value);
}
