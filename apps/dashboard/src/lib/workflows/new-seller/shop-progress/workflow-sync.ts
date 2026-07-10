import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import type { ListingWorkflowState } from "@/lib/workflows/new-seller/listing/state-machine";
import { loadShopProgress, updateListingWidgetState } from "./tracker";
import type { ListingWidgetState } from "./types";

export function deriveWidgetStateFromWorkflow(
  state: ListingWorkflowState,
): ListingWidgetState {
  if (state.step === "draft_review" || state.step === "export_placeholder") {
    return "draft_generated";
  }

  if (state.selectedDistributorId) {
    return "distributor_known";
  }

  return "no_distributor";
}

export function syncShopProgressFromWorkflow(
  personaId: PersonaId,
  state: ListingWorkflowState,
): void {
  const current = loadShopProgress(personaId);
  if (current.widgetState === "published_stub") return;

  updateListingWidgetState(personaId, deriveWidgetStateFromWorkflow(state));
}
