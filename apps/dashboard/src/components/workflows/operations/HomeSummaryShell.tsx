"use client";

import type { PersonaId, SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import { useHomeJourneyHighlight } from "@/lib/operations/use-home-journey-highlight";
import { useOperationsPipeline } from "@/lib/operations/use-operations-pipeline";

import { TodaysReportPanel } from "@/components/home/todays-report";

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
  const { highlightDomain, highlightedMetricKey, anchor } = useHomeJourneyHighlight();

  return (
    <section data-testid="home-summary-shell">
      <div className="seller-home-grid" data-testid="seller-home-grid">
        <aside className="seller-home-sidebar" data-testid="seller-home-sidebar">
          <ShopInfoCard
            metadata={unifiedModel.shop_metadata}
            dataTestId="shop-info-sidebar-card"
            statusTestId="shop-info-sidebar-status"
          />
        </aside>
        <div className="seller-home-main" data-testid="seller-home-main">
          <TodaysReportPanel
            model={unifiedModel}
            profile={pipeline.shopProfile}
            recommendations={workflowRecommendations.recommended_workflows}
            highlightDomain={highlightDomain}
            highlightedMetricKey={highlightedMetricKey}
          />
          <ShopHealthCard
            model={unifiedModel}
            recommendations={workflowRecommendations.recommended_workflows}
            highlightedMetricKey={
              anchor?.reportDomain === "shop_health" ? highlightedMetricKey : null
            }
            shopHealthMetricKey={
              anchor?.reportDomain === "shop_health" ? anchor.metricKey : null
            }
          />
        </div>
      </div>
    </section>
  );
}
