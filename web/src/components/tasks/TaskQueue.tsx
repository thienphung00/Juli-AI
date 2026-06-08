"use client";

import type { MockTask, PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import { useTaskExecutor } from "@/lib/task-executor/use-task-executor";
import { ListingWorkflowPanel } from "@/components/workflows/new-seller/listing";
import { DemoModeNotice } from "./DemoModeNotice";
import { TaskCard } from "./TaskCard";
import { TaskFeedbackBanner } from "./TaskFeedbackBanner";

export function TaskQueue({
  tasks,
  personaId,
}: {
  tasks: MockTask[];
  personaId: PersonaId;
}) {
  const {
    activeTasks,
    feedback,
    clearFeedback,
    approveTask,
    dismissTask,
    listingWorkflowOpen,
    closeListingWorkflow,
  } = useTaskExecutor(tasks, { personaId });

  return (
    <section className="space-y-4" data-testid="task-queue">
      {listingWorkflowOpen && (
        <ListingWorkflowPanel
          personaId={personaId}
          onClose={closeListingWorkflow}
        />
      )}
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
                personaId={personaId}
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
