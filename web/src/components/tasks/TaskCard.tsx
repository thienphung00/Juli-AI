"use client";

import { useEffect, useRef, useState } from "react";
import { MoreVertical } from "lucide-react";
import type { MockTask, PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import { formatVND } from "@/lib/format";
import { taskSeverityLabel, taskSeverityStyle } from "@/lib/task-executor";
import { trackTaskClicked } from "@/lib/ux-analytics";

export function TaskCard({
  task,
  personaId,
  onApprove,
  onDismiss,
  onViewEvidence,
  disabled = false,
}: {
  task: MockTask;
  personaId: PersonaId;
  onApprove: (taskId: string) => void;
  onDismiss: (taskId: string) => void;
  onViewEvidence?: (taskId: string) => void;
  disabled?: boolean;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const severityStyle = taskSeverityStyle(task.severity);

  useEffect(() => {
    if (!menuOpen) return;

    const onPointerDown = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [menuOpen]);

  const handleCardEngagement = (target: EventTarget | null) => {
    if (!(target instanceof HTMLElement)) return;
    if (
      target.closest(
        '[data-testid="task-approve"], [data-testid="task-dismiss"], [data-testid="task-more-menu"], [data-testid="task-view-evidence"]',
      )
    ) {
      return;
    }
    trackTaskClicked({
      workflow: task.workflow,
      task_type: task.type,
      persona_id: personaId,
    });
  };

  return (
    <article
      className="card p-4"
      data-testid="task-card"
      data-task-id={task.id}
      aria-labelledby={`task-title-${task.id}`}
      onClick={(event) => handleCardEngagement(event.target)}
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
            className="text-xs font-medium"
            style={{ color: "var(--success)" }}
            data-testid="task-gmv-impact"
          >
            +{formatVND(task.estimated_impact_vnd)}
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

      <div className="mt-4 flex gap-2">
        <button
          type="button"
          className="btn-primary min-h-[44px] flex-1 disabled:opacity-50"
          disabled={disabled}
          onClick={() => onApprove(task.id)}
          data-testid="task-approve"
        >
          {task.cta_label}
        </button>

        <div className="relative shrink-0" ref={menuRef}>
          <button
            type="button"
            aria-label="Tùy chọn nhiệm vụ"
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            className="flex h-11 w-11 items-center justify-center rounded-xl border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] disabled:opacity-50"
            style={{
              borderColor: "var(--border)",
              color: "var(--foreground)",
              background: "transparent",
            }}
            disabled={disabled}
            onClick={() => setMenuOpen((open) => !open)}
            data-testid="task-more-menu"
          >
            <MoreVertical size={18} aria-hidden />
          </button>

          {menuOpen && (
          <div
            role="menu"
            className="absolute right-0 top-full z-10 mt-1 min-w-[10rem] rounded-xl border py-1 shadow-lg"
            style={{
              borderColor: "var(--border)",
              background: "var(--card)",
            }}
          >
            {onViewEvidence && (
              <button
                type="button"
                role="menuitem"
                className="w-full px-3 py-2.5 text-left text-sm transition-colors hover:opacity-80"
                style={{ color: "var(--muted-foreground)" }}
                disabled={disabled}
                onClick={() => {
                  setMenuOpen(false);
                  onViewEvidence(task.id);
                }}
                data-testid="task-view-evidence"
              >
                Xem bằng chứng
              </button>
            )}
            <button
              type="button"
              role="menuitem"
              className="w-full px-3 py-2.5 text-left text-sm font-semibold transition-colors hover:opacity-80"
              style={{ color: "var(--foreground)" }}
              disabled={disabled}
              onClick={() => {
                setMenuOpen(false);
                onDismiss(task.id);
              }}
              data-testid="task-dismiss"
            >
              Bỏ qua
            </button>
          </div>
          )}
        </div>
      </div>
    </article>
  );
}
