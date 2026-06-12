"use client";

import { useMemo, useState } from "react";

import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";
import type { PersonaId, SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import { buildInProgressDecisions } from "@/lib/decisions/in-progress";
import { useOperationsApproval } from "@/lib/operations/use-operations-approval";
import { useOperationsPipeline } from "@/lib/operations/use-operations-pipeline";
import { OutcomeTrackingView } from "@/components/workflows/operations/OutcomeTrackingView";
import { TaskExecutorModals } from "@/components/tasks/TaskExecutorModals";

import { InProgressDecisionCard } from "./InProgressDecisionCard";

export function DecisionsInProgressShell({
  persona,
  personaId,
}: {
  persona: SellerPersona;
  personaId: PersonaId;
}) {
  const [viewingOutcomeWorkflowId, setViewingOutcomeWorkflowId] =
    useState<ValidatedWorkflowId | null>(null);

  const pipeline = useOperationsPipeline({ personaId });
  const { healthResults, workflowRecommendations } = pipeline;

  const approval = useOperationsApproval({
    persona,
    personaId,
    health: healthResults,
    recommendations: workflowRecommendations.recommended_workflows,
  });

  const inProgressDecisions = useMemo(() => {
    return buildInProgressDecisions(workflowRecommendations.recommended_workflows, {
      approvalSession: approval.session,
      lifecycleSession: approval.lifecycleSession,
      executorSession: approval.executor.session,
      persona,
      health: healthResults,
    });
  }, [
    approval.session,
    approval.lifecycleSession,
    approval.executor.session,
    healthResults,
    persona,
    workflowRecommendations.recommended_workflows,
  ]);

  if (viewingOutcomeWorkflowId) {
    return (
      <section className="space-y-4" data-testid="decisions-in-progress-shell">
        <OutcomeTrackingView
          workflowId={viewingOutcomeWorkflowId}
          onBack={() => setViewingOutcomeWorkflowId(null)}
        />
      </section>
    );
  }

  if (inProgressDecisions.length === 0) {
    return (
      <section className="space-y-4" data-testid="decisions-in-progress-shell">
        <div
          className="rounded-2xl border p-6 text-center"
          style={{ borderColor: "var(--border)", background: "var(--card)" }}
          data-testid="decisions-in-progress-empty"
        >
          <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
            Chưa có quyết định đang thực hiện. Phê duyệt gợi ý ở tab Đề xuất để bắt đầu.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="space-y-4" data-testid="decisions-in-progress-shell">
      <TaskExecutorModals
        personaId={personaId}
        leakagePersona={personaId === "leakage" ? persona : undefined}
        executor={approval.executor}
      />

      <ul className="space-y-3" data-testid="decisions-in-progress-list">
        {inProgressDecisions.map((decision) => (
          <li key={decision.id}>
            <InProgressDecisionCard
              decision={decision}
              onViewOutcome={
                decision.status === "completed"
                  ? () => setViewingOutcomeWorkflowId(decision.workflow_id)
                  : undefined
              }
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
