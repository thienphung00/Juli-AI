"use client";

import type { PersonaId, SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import {
  takeTopDecisions,
  toDecisionsFromRecommendations,
} from "@/lib/decisions";
import { computeShopHealthSummary } from "@/lib/operations/health-summary";
import { useOperationsPipeline } from "@/lib/operations/use-operations-pipeline";

import { RecommendedDecisionsPreview } from "./RecommendedDecisionsPreview";
import { ShopHealthHero } from "./ShopHealthHero";

export function HomeSummaryShell({
  persona,
  personaId,
}: {
  persona: SellerPersona;
  personaId: PersonaId;
}) {
  const pipeline = useOperationsPipeline({ personaId });
  const { healthResults, workflowRecommendations, shopProfile } = pipeline;
  const healthSummary = computeShopHealthSummary(shopProfile, healthResults);

  const topDecisions = takeTopDecisions(
    toDecisionsFromRecommendations(workflowRecommendations.recommended_workflows),
    3,
  );

  return (
    <section className="space-y-4" data-testid="home-summary-shell">
      <ShopHealthHero
        shopName={persona.profile.shop_name}
        profile={shopProfile}
        health={healthResults}
        summary={healthSummary}
      />

      <RecommendedDecisionsPreview decisions={topDecisions} />
    </section>
  );
}
