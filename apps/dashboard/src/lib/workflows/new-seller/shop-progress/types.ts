import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";

/** Task card widget states for the list_products listing journey (issue #157). */
export type ListingWidgetState =
  | "no_distributor"
  | "distributor_known"
  | "draft_generated"
  | "published_stub";

export type ReadinessScoreBucket = "low" | "medium" | "high";

export interface ShopProgressSession {
  version: 1;
  personaId: PersonaId;
  activeListingCount: number;
  widgetState: ListingWidgetState;
}

export interface ListingMilestone {
  count: number;
  target: number;
  percent: number;
  remaining: number;
}
