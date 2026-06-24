"use client";

import { useState } from "react";
import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";
import { TaskDismissModal } from "@/components/tasks/TaskDismissModal";
import { TaskExecutorModals } from "@/components/tasks/TaskExecutorModals";
import { TaskFeedbackBanner } from "@/components/tasks/TaskFeedbackBanner";
import type { PersonaId, SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import { useJourneyHighlight } from "@/lib/operations/use-journey-highlight";
import { useOperationsApproval } from "@/lib/operations/use-operations-approval";
import { useOperationsPipeline } from "@/lib/operations/use-operations-pipeline";

import {
  ApprovalGateToolbar,
  OperationsRecommendationsList,
} from "./ApprovalGate";
import { OutcomeTrackingView } from "./OutcomeTrackingView";

export function OperationsApprovalShell({
  persona,
  personaId,
  shellTestId = "operations-approval-shell",
}: {
  persona: SellerPersona;
  personaId: PersonaId;
  shellTestId?: string;
}) {
  const [viewingOutcomeWorkflowId, setViewingOutcomeWorkflowId] =
    useState<ValidatedWorkflowId | null>(null);

  const pipeline = useOperationsPipeline({ personaId });
  const { healthResults, workflowRecommendations } = pipeline;
  const highlightedWorkflowId = useJourneyHighlight(
    workflowRecommendations.recommended_workflows.map(
      (recommendation) => recommendation.workflow_id,
    ),
  );

  const approval = useOperationsApproval({
    persona,
    personaId,
    health: healthResults,
    recommendations: workflowRecommendations.recommended_workflows,
  });

  const {
    pendingRecommendations,
    selectedIds,
    toggleSelection,
    selectAllPending,
    approveSelected,
    approveAllPending,
    approveWorkflow,
    requestRejectWorkflow,
    cancelRejectWorkflow,
    confirmRejectWorkflow,
    rejectModalWorkflowId,
    feedback,
    clearFeedback,
    executor,
    getDisposition,
  } = approval;

  return (
    <section className="space-y-4" data-testid={shellTestId}>
      <TaskExecutorModals
        personaId={personaId}
        leakagePersona={personaId === "leakage" ? persona : undefined}
        executor={executor}
      />

      {rejectModalWorkflowId !== null && (
        <TaskDismissModal
          onCancel={cancelRejectWorkflow}
          onConfirm={confirmRejectWorkflow}
        />
      )}

      {feedback && (
        <TaskFeedbackBanner feedback={feedback} onDismiss={clearFeedback} />
      )}

      {viewingOutcomeWorkflowId ? (
        <OutcomeTrackingView
          workflowId={viewingOutcomeWorkflowId}
          onBack={() => setViewingOutcomeWorkflowId(null)}
        />
      ) : (
        <>
          <OperationsRecommendationsList
            recommendations={workflowRecommendations.recommended_workflows}
            health={healthResults}
            personaId={personaId}
            getDisposition={getDisposition}
            selectedIds={selectedIds}
            highlightedWorkflowId={highlightedWorkflowId}
            onToggleSelect={toggleSelection}
            onApprove={approveWorkflow}
            onReject={requestRejectWorkflow}
            onViewOutcome={setViewingOutcomeWorkflowId}
          />

          <ApprovalGateToolbar
            pendingCount={pendingRecommendations.length}
            selectedCount={selectedIds.size}
            onApproveAll={approveAllPending}
            onApproveSelected={approveSelected}
            onSelectAll={selectAllPending}
          />
        </>
      )}
    </section>
  );
}
