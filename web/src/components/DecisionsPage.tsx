"use client";

import { useEffect, useState } from "react";

import { AuthenticatedShell } from "./AuthenticatedShell";
import { DecisionsInProgressShell } from "./decisions/DecisionsInProgressShell";
import { DecisionsSubTabs, type DecisionsSubTab } from "./decisions/DecisionsSubTabs";
import { DecisionsWorkflowTemplatesShell } from "./decisions/DecisionsWorkflowTemplatesShell";
import { OperationsApprovalShell } from "./workflows/operations/OperationsApprovalShell";
import { restoreDecisionsRecommendedScroll } from "@/lib/decisions/detail-content";
import { useDemoPersona } from "@/lib/demo-persona-context";

function DecisionsSkeleton() {
  return (
    <div className="space-y-4" data-testid="decisions-shell-skeleton" aria-busy="true">
      <div className="skeleton h-10 w-full" />
      <div className="skeleton h-24 w-full" />
      <div className="skeleton h-40 w-full" />
    </div>
  );
}

export function DecisionsPage() {
  const { persona, personaId, isReady } = useDemoPersona();
  const [activeTab, setActiveTab] = useState<DecisionsSubTab>("recommended");

  useEffect(() => {
    restoreDecisionsRecommendedScroll();
  }, []);

  return (
    <AuthenticatedShell title="Quyết định">
      <DecisionsSubTabs activeTab={activeTab} onTabChange={setActiveTab} />

      {!isReady ? (
        <DecisionsSkeleton />
      ) : activeTab === "recommended" ? (
        <OperationsApprovalShell
          persona={persona}
          personaId={personaId}
          shellTestId="decisions-recommended-shell"
        />
      ) : activeTab === "in_progress" ? (
        <DecisionsInProgressShell persona={persona} personaId={personaId} />
      ) : (
        <DecisionsWorkflowTemplatesShell />
      )}
    </AuthenticatedShell>
  );
}
