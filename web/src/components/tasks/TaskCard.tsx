"use client";

import type { MockTask } from "@/lib/mock-data/seller-personas/schemas";
import { formatVND } from "@/lib/format";
import { taskSeverityLabel, taskSeverityStyle } from "@/lib/task-executor";

export function TaskCard({
  task,
  onApprove,
  onDismiss,
  disabled = false,
}: {
  task: MockTask;
  onApprove: (taskId: string) => void;
  onDismiss: (taskId: string) => void;
  disabled?: boolean;
}) {
  const severityStyle = taskSeverityStyle(task.severity);

  return (
    <article
      className="card p-4"
      data-testid="task-card"
      data-task-id={task.id}
      aria-labelledby={`task-title-${task.id}`}
    >
      <div className="flex items-start justify-between gap-2">
        <span
          className="badge text-xs font-semibold"
          style={severityStyle}
          data-testid="task-severity"
        >
          {taskSeverityLabel(task.severity)}
        </span>
        {task.estimated_impact_vnd !== null && (
          <span
            className="text-xs font-semibold"
            style={{ color: "#10b981" }}
            data-testid="task-gmv-impact"
          >
            +{formatVND(task.estimated_impact_vnd)} GMV dự kiến
          </span>
        )}
      </div>

      <h3
        id={`task-title-${task.id}`}
        className="mt-2 text-sm font-semibold"
        data-testid="task-title"
      >
        {task.title}
      </h3>

      <p className="mt-2 text-sm" style={{ color: "var(--muted-foreground)" }} data-testid="task-body">
        {task.body}
      </p>

      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        <button
          type="button"
          className="flex-1 rounded-xl px-3 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
          style={{ background: "linear-gradient(135deg, #ff006e 0%, #ff4d94 100%)" }}
          disabled={disabled}
          onClick={() => onApprove(task.id)}
          data-testid="task-approve"
        >
          {task.cta_label}
        </button>
        <button
          type="button"
          className="flex-1 rounded-xl border px-3 py-2.5 text-sm font-semibold disabled:opacity-50"
          style={{
            borderColor: "var(--border)",
            color: "var(--foreground)",
            background: "transparent",
          }}
          disabled={disabled}
          onClick={() => onDismiss(task.id)}
          data-testid="task-dismiss"
        >
          Bỏ qua
        </button>
      </div>
    </article>
  );
}
