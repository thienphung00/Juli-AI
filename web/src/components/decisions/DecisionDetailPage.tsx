"use client";

import Link from "next/link";

import { AuthenticatedShell } from "@/components/AuthenticatedShell";
import { getRequiredInputsForWorkflow, isValidatedWorkflowId } from "@/lib/decisions";
import { useDemoPersona } from "@/lib/demo-persona-context";
import { useOperationsPipeline } from "@/lib/operations/use-operations-pipeline";

import { DecisionDetailFlow } from "./DecisionDetailFlow";

function DecisionDetailSkeleton() {
  return (
    <div className="space-y-4" data-testid="decision-detail-skeleton" aria-busy="true">
      <div className="skeleton h-8 w-40" />
      <div className="skeleton h-10 w-full" />
      <div className="skeleton h-48 w-full" />
    </div>
  );
}

export function DecisionDetailPage({ decisionId }: { decisionId: string }) {
  const { persona, personaId, isReady } = useDemoPersona();
  const pipeline = useOperationsPipeline({ personaId });

  if (!isValidatedWorkflowId(decisionId)) {
    return (
      <AuthenticatedShell title="Quyết định">
        <div
          className="rounded-2xl border p-6 text-center"
          style={{ borderColor: "var(--border)", background: "var(--card)" }}
          data-testid="decision-detail-not-found"
        >
          <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
            Không tìm thấy quyết định này.
          </p>
          <Link href="/decisions" className="btn-primary mt-4 inline-flex">
            Về Quyết định
          </Link>
        </div>
      </AuthenticatedShell>
    );
  }

  const recommendation = pipeline.workflowRecommendations.recommended_workflows.find(
    (item) => item.workflow_id === decisionId,
  );

  return (
    <AuthenticatedShell title="Chi tiết quyết định">
      {!isReady ? (
        <DecisionDetailSkeleton />
      ) : !recommendation ? (
        <div
          className="rounded-2xl border p-6 text-center"
          style={{ borderColor: "var(--border)", background: "var(--card)" }}
          data-testid="decision-detail-not-found"
        >
          <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
            Quyết định không có trong danh sách đề xuất cho shop này.
          </p>
          <Link href="/decisions" className="btn-primary mt-4 inline-flex">
            Về Quyết định
          </Link>
        </div>
      ) : (
        <DecisionDetailFlow
          recommendation={recommendation}
          health={pipeline.healthResults}
          persona={persona}
          personaId={personaId}
          requiredInputs={getRequiredInputsForWorkflow(decisionId)}
        />
      )}
    </AuthenticatedShell>
  );
}
