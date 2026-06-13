"use client";

import type { PersonaId, SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import { useOperationsPipeline } from "@/lib/operations/use-operations-pipeline";

import { TodaysReportPanel } from "@/components/home/todays-report";

import { ShopHealthCard } from "./ShopHealthCard";

export function HomeSummaryShell({
  personaId,
}: {
  persona: SellerPersona;
  personaId: PersonaId;
}) {
  const pipeline = useOperationsPipeline({ personaId });
  const { unifiedModel, workflowRecommendations } = pipeline;

  return (
    <section className="space-y-4" data-testid="home-summary-shell">
      <TodaysReportPanel
        model={unifiedModel}
        profile={pipeline.shopProfile}
        recommendations={workflowRecommendations.recommended_workflows}
      />
      <ShopHealthCard
        model={unifiedModel}
        recommendations={workflowRecommendations.recommended_workflows}
      />
    </section>
  );
}
