"use client";

import { takeTopDecisions, toDecisionsFromRecommendations } from "@/lib/decisions";
import type { PersonaId, SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import { buildRecentProgressItems } from "@/lib/operations/recent-progress";
import { useOperationsPipeline } from "@/lib/operations/use-operations-pipeline";

import { RecentProgressCard } from "@/components/home/RecentProgressCard";
import { TodaysReportPanel } from "@/components/home/todays-report";

import { RecommendedDecisionsPreview } from "./RecommendedDecisionsPreview";
import { ShopHealthCard } from "./ShopHealthCard";
import { ShopInfoCard } from "./ShopInfoCard";

export function HomeSummaryShell({
  personaId,
}: {
  persona: SellerPersona;
  personaId: PersonaId;
}) {
  const pipeline = useOperationsPipeline({ personaId });
  const { unifiedModel, workflowRecommendations } = pipeline;

  const recentProgress = buildRecentProgressItems(
    workflowRecommendations.recommended_workflows,
  );
  const previewDecisions = takeTopDecisions(
    toDecisionsFromRecommendations(workflowRecommendations.recommended_workflows),
    3,
  );

  return (
    <section className="space-y-4" data-testid="home-summary-shell">
      <ShopInfoCard metadata={unifiedModel.shop_metadata} />
      <ShopHealthCard
        model={unifiedModel}
        recommendations={workflowRecommendations.recommended_workflows}
      />
      <TodaysReportPanel
        model={unifiedModel}
        profile={pipeline.shopProfile}
        recommendations={workflowRecommendations.recommended_workflows}
      />
      <RecommendedDecisionsPreview decisions={previewDecisions} />
      <RecentProgressCard items={recentProgress} />
    </section>
  );
}
