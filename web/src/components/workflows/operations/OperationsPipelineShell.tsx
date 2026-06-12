"use client";

import { TaskDismissModal } from "@/components/tasks/TaskDismissModal";
import { TaskExecutorModals } from "@/components/tasks/TaskExecutorModals";
import { TaskFeedbackBanner } from "@/components/tasks/TaskFeedbackBanner";
import type { PersonaId, SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import { computeShopHealthSummary } from "@/lib/operations/health-summary";
import { useOperationsApproval } from "@/lib/operations/use-operations-approval";
import { useOperationsPipeline } from "@/lib/operations/use-operations-pipeline";

import {
  ApprovalGateToolbar,
  OperationsRecommendationsList,
} from "./ApprovalGate";
import { ShopHealthHero } from "./ShopHealthHero";

export function OperationsPipelineShell({
  persona,
  personaId,
}: {
  persona: SellerPersona;
  personaId: PersonaId;
}) {
  const pipeline = useOperationsPipeline({ personaId });
  const { healthResults, workflowRecommendations, shopProfile } = pipeline;
  const healthSummary = computeShopHealthSummary(shopProfile, healthResults);

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
    <section className="space-y-4" data-testid="operations-pipeline-shell">
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

      <ShopHealthHero
        shopName={persona.profile.shop_name}
        profile={shopProfile}
        health={healthResults}
        summary={healthSummary}
      />

      <ApprovalGateToolbar
        pendingCount={pendingRecommendations.length}
        selectedCount={selectedIds.size}
        onApproveAll={approveAllPending}
        onApproveSelected={approveSelected}
        onSelectAll={selectAllPending}
      />

      <OperationsRecommendationsList
        recommendations={workflowRecommendations.recommended_workflows}
        health={healthResults}
        getDisposition={getDisposition}
        selectedIds={selectedIds}
        onToggleSelect={toggleSelection}
        onApprove={approveWorkflow}
        onReject={requestRejectWorkflow}
      />
    </section>
  );
}
