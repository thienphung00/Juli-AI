"use client";

import { useState } from "react";
import type { MockTask, SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import { useTaskExecutor } from "@/lib/task-executor/use-task-executor";
import { DemoModeNotice } from "@/components/tasks/DemoModeNotice";
import { TaskCard } from "@/components/tasks/TaskCard";
import { TaskExecutorModals } from "@/components/tasks/TaskExecutorModals";
import { TaskFeedbackBanner } from "@/components/tasks/TaskFeedbackBanner";
import { EvidenceDrawer } from "./EvidenceDrawer";

export function LeakageCopilotPanel({
  persona,
  tasks,
}: {
  persona: SellerPersona;
  tasks: MockTask[];
}) {
  const executor = useTaskExecutor(tasks, { personaId: persona.profile.id });
  const {
    activeTasks,
    feedback,
    clearFeedback,
    approveTask,
    requestDismissTask,
  } = executor;
  const [evidenceTaskId, setEvidenceTaskId] = useState<string | null>(null);

  const evidenceTask =
    evidenceTaskId !== null
      ? activeTasks.find((t) => t.id === evidenceTaskId) ??
        tasks.find((t) => t.id === evidenceTaskId) ??
        null
      : null;

  const hasNoSignals = tasks.length === 0;

  return (
    <section className="space-y-4" data-testid="leakage-copilot-panel">
      <TaskExecutorModals
        personaId={persona.profile.id}
        leakagePersona={persona}
        executor={executor}
      />
      <header>
        <h2 className="text-sm font-semibold">Phát hiện rò rỉ doanh thu</h2>
        <p className="text-muted mt-1 text-xs">
          Bất thường được xếp hạng theo mức độ nghiêm trọng và tác động GMV ước tính
        </p>
      </header>

      <DemoModeNotice />

      {feedback && (
        <TaskFeedbackBanner feedback={feedback} onDismiss={clearFeedback} />
      )}

      {hasNoSignals ? (
        <p
          className="rounded-xl border px-4 py-6 text-center text-sm"
          style={{ borderColor: "var(--border)", color: "var(--muted-foreground)" }}
          data-testid="leakage-empty-state"
        >
          Không phát hiện rò rỉ tuần này
        </p>
      ) : activeTasks.length === 0 ? (
        <p
          className="rounded-xl border px-4 py-6 text-center text-sm"
          style={{ borderColor: "var(--border)", color: "var(--muted-foreground)" }}
          data-testid="task-queue-empty"
        >
          Không còn nhiệm vụ đang chờ xử lý trong phiên này.
        </p>
      ) : (
        <ul className="space-y-3" data-testid="leakage-task-list">
          {activeTasks.map((task) => (
            <li key={task.id} className="space-y-2">
              <TaskCard
                task={task}
                personaId={persona.profile.id}
                onApprove={approveTask}
                onDismiss={requestDismissTask}
              />
              <button
                type="button"
                className="w-full rounded-xl border px-3 py-2 text-sm font-semibold"
                style={{
                  borderColor: "var(--border)",
                  color: "var(--foreground)",
                  background: "transparent",
                }}
                onClick={() => setEvidenceTaskId(task.id)}
                data-testid="task-view-evidence"
              >
                Xem bằng chứng
              </button>
              {evidenceTask?.id === task.id && (
                <EvidenceDrawer
                  task={task}
                  persona={persona}
                  onClose={() => setEvidenceTaskId(null)}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
