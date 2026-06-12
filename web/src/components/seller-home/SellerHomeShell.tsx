"use client";

import { useDemoPersona } from "@/lib/demo-persona-context";

import { OperationsPipelineShell } from "@/components/workflows/operations/OperationsPipelineShell";

function SellerHomeSkeleton() {
  return (
    <div className="space-y-4" data-testid="seller-home-skeleton" aria-busy="true">
      <div className="skeleton h-24 w-full" />
      <div className="skeleton h-20 w-full" />
      <div className="skeleton h-40 w-full" />
    </div>
  );
}

export function SellerHomeShell() {
  const { persona, personaId, isReady } = useDemoPersona();

  if (!isReady) {
    return <SellerHomeSkeleton />;
  }

  return (
    <div className="seller-home-grid" data-testid="seller-home-shell">
      <OperationsPipelineShell persona={persona} personaId={personaId} />
    </div>
  );
}
