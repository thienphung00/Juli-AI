"use client";

import type { PersonaId, SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import { computeShopHealthSummary } from "@/lib/operations/health-summary";
import { useOperationsPipeline } from "@/lib/operations/use-operations-pipeline";

import { OperationsApprovalShell } from "./OperationsApprovalShell";
import { ShopHealthHero } from "./ShopHealthHero";

/** Legacy composite shell — shop health + approval. Production approval lives on `/decisions`. */
export function OperationsPipelineShell({
  persona,
  personaId,
}: {
  persona: SellerPersona;
  personaId: PersonaId;
}) {
  const pipeline = useOperationsPipeline({ personaId });
  const { healthResults, shopProfile } = pipeline;
  const healthSummary = computeShopHealthSummary(shopProfile, healthResults);

  return (
    <section className="space-y-4" data-testid="operations-pipeline-shell">
      <ShopHealthHero
        shopName={persona.profile.shop_name}
        profile={shopProfile}
        health={healthResults}
        summary={healthSummary}
      />

      <OperationsApprovalShell persona={persona} personaId={personaId} />
    </section>
  );
}
