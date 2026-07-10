"use client";

import type { PersonaId, SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import { useOperationsPipeline } from "@/lib/operations/use-operations-pipeline";

import { OperationsApprovalShell } from "./OperationsApprovalShell";
import { ShopHealthCard } from "./ShopHealthCard";
import { ShopInfoCard } from "./ShopInfoCard";

/** Legacy composite shell — shop health + approval. Production approval lives on `/decisions`. */
export function OperationsPipelineShell({
  persona: _persona,
  personaId,
}: {
  persona: SellerPersona;
  personaId: PersonaId;
}) {
  const pipeline = useOperationsPipeline({ personaId });
  const { unifiedModel } = pipeline;

  return (
    <section className="space-y-4" data-testid="operations-pipeline-shell">
      <ShopInfoCard metadata={unifiedModel.shop_metadata} />
      <ShopHealthCard model={unifiedModel} />
      <OperationsApprovalShell persona={_persona} personaId={personaId} />
    </section>
  );
}
