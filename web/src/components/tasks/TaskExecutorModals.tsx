"use client";

import type { PersonaId, SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import { ListingWorkflowPanel } from "@/components/workflows/new-seller/listing";
import { LeakageWorkflowPanel } from "@/components/workflows/leakage";
import { TaskDismissModal } from "./TaskDismissModal";
import type { TaskDismissReason } from "@/lib/task-executor/dismiss-reasons";

export interface TaskExecutorModalState {
  listingWorkflowOpen: boolean;
  closeListingWorkflow: () => void;
  leakageWorkflowTaskId: string | null;
  closeLeakageWorkflow: () => void;
  completeLeakageWorkflow: () => void;
  dismissModalTaskId: string | null;
  cancelDismissTask: () => void;
  confirmDismissTask: (reason: TaskDismissReason, note?: string) => void;
}

export function TaskExecutorModals({
  personaId,
  leakagePersona,
  executor,
}: {
  personaId: PersonaId;
  leakagePersona?: SellerPersona;
  executor: TaskExecutorModalState;
}) {
  const {
    listingWorkflowOpen,
    closeListingWorkflow,
    leakageWorkflowTaskId,
    closeLeakageWorkflow,
    completeLeakageWorkflow,
    dismissModalTaskId,
    cancelDismissTask,
    confirmDismissTask,
  } = executor;

  return (
    <>
      {listingWorkflowOpen && (
        <ListingWorkflowPanel personaId={personaId} onClose={closeListingWorkflow} />
      )}
      {leakageWorkflowTaskId !== null && (
        <LeakageWorkflowPanel
          taskId={leakageWorkflowTaskId}
          persona={leakagePersona}
          onClose={closeLeakageWorkflow}
          onComplete={completeLeakageWorkflow}
        />
      )}
      {dismissModalTaskId !== null && (
        <TaskDismissModal
          onCancel={cancelDismissTask}
          onConfirm={confirmDismissTask}
        />
      )}
    </>
  );
}
