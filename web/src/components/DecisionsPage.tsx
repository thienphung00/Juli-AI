"use client";

import { useEffect, useState } from "react";

import { AuthenticatedShell } from "./AuthenticatedShell";
import { DecisionsSubTabs, type DecisionsSubTab } from "./decisions/DecisionsSubTabs";
import { OperationsApprovalShell } from "./workflows/operations/OperationsApprovalShell";
import { restoreDecisionsRecommendedScroll } from "@/lib/decisions/detail-content";
import { useDemoPersona } from "@/lib/demo-persona-context";

function DecisionsTabPlaceholder({
  testId,
  message,
}: {
  testId: string;
  message: string;
}) {
  return (
    <div
      className="rounded-2xl border p-6 text-center"
      style={{ borderColor: "var(--border)", background: "var(--card)" }}
      data-testid={testId}
    >
      <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
        {message}
      </p>
    </div>
  );
}

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
        <DecisionsTabPlaceholder
          testId="decisions-in-progress-placeholder"
          message="Quyết định đang thực hiện sẽ có trong bản cập nhật tiếp theo."
        />
      ) : (
        <DecisionsTabPlaceholder
          testId="decisions-templates-placeholder"
          message="Mẫu quy trình sẽ có trong bản cập nhật tiếp theo."
        />
      )}
    </AuthenticatedShell>
  );
}
