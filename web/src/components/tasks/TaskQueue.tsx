"use client";

import type { MockTask } from "@/lib/mock-data/seller-personas/schemas";
import { useTaskExecutor } from "@/lib/task-executor/use-task-executor";
import { DemoModeNotice } from "./DemoModeNotice";
import { TaskCard } from "./TaskCard";
import { TaskFeedbackBanner } from "./TaskFeedbackBanner";

export function TaskQueue({ tasks }: { tasks: MockTask[] }) {
  const { activeTasks, feedback, clearFeedback, approveTask, dismissTask } =
    useTaskExecutor(tasks);

  return (
    <section className="space-y-4" data-testid="task-queue">
      <DemoModeNotice />

      {feedback && (
        <TaskFeedbackBanner feedback={feedback} onDismiss={clearFeedback} />
      )}

      {activeTasks.length === 0 ? (
        <p
          className="rounded-xl border px-4 py-6 text-center text-sm"
          style={{ borderColor: "var(--border)", color: "var(--muted-foreground)" }}
          data-testid="task-queue-empty"
        >
          Không còn nhiệm vụ đang chờ xử lý trong phiên này.
        </p>
      ) : (
        <ul className="space-y-3" data-testid="task-queue-list">
          {activeTasks.map((task) => (
            <li key={task.id}>
              <TaskCard
                task={task}
                onApprove={approveTask}
                onDismiss={dismissTask}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
