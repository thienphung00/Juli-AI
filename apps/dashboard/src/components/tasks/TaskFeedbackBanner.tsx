"use client";

import type { TaskFeedback } from "@/lib/task-executor";

export function TaskFeedbackBanner({
  feedback,
  onDismiss,
}: {
  feedback: TaskFeedback;
  onDismiss: () => void;
}) {
  return (
    <div
      role="status"
      className="rounded-xl px-3 py-2 text-sm"
      style={{
        background:
          feedback.kind === "approved" ? "#10b98120" : "var(--muted)",
        color: "var(--foreground)",
      }}
      data-testid={`task-feedback-${feedback.kind}`}
    >
      <div className="flex items-start justify-between gap-2">
        <p>{feedback.message}</p>
        <button
          type="button"
          className="shrink-0 text-xs font-medium underline"
          style={{ color: "var(--muted-foreground)" }}
          onClick={onDismiss}
          aria-label="Đóng thông báo"
        >
          Đóng
        </button>
      </div>
    </div>
  );
}
