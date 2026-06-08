import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import { READINESS_EXPORT_THRESHOLD } from "@/lib/workflows/new-seller/listing/constants";
import { computeListingMilestone } from "./milestone";
import {
  clearShopProgressSession,
  createDefaultShopProgress,
  loadShopProgressSession,
  notifyShopProgressUpdated,
  saveShopProgressSession,
} from "./session-store";
import type {
  ListingMilestone,
  ListingWidgetState,
  ReadinessScoreBucket,
  ShopProgressSession,
} from "./types";

export function loadShopProgress(personaId: PersonaId): ShopProgressSession {
  return loadShopProgressSession(personaId);
}

export function updateListingWidgetState(
  personaId: PersonaId,
  widgetState: ListingWidgetState,
): ShopProgressSession {
  const session = loadShopProgressSession(personaId);
  const next: ShopProgressSession = { ...session, widgetState };
  saveShopProgressSession(next);
  notifyShopProgressUpdated(personaId);
  return next;
}

export function incrementActiveListingCount(personaId: PersonaId): ShopProgressSession {
  const session = loadShopProgressSession(personaId);
  const next: ShopProgressSession = {
    ...session,
    activeListingCount: session.activeListingCount + 1,
  };
  saveShopProgressSession(next);
  notifyShopProgressUpdated(personaId);
  return next;
}

/** Atomic export completion: increment listing count and mark Published-stub. */
export function recordExportCompleted(personaId: PersonaId): ShopProgressSession {
  const session = loadShopProgressSession(personaId);
  const next: ShopProgressSession = {
    ...session,
    activeListingCount: session.activeListingCount + 1,
    widgetState: "published_stub",
  };
  saveShopProgressSession(next);
  notifyShopProgressUpdated(personaId);
  return next;
}

export function clearShopProgress(personaId: PersonaId): void {
  clearShopProgressSession(personaId);
  notifyShopProgressUpdated(personaId);
}

export function getListingMilestoneForPersona(personaId: PersonaId): ListingMilestone {
  const session = loadShopProgressSession(personaId);
  return computeListingMilestone(session.activeListingCount);
}

export function getReadinessScoreBucket(score: number): ReadinessScoreBucket {
  if (score >= READINESS_EXPORT_THRESHOLD) return "high";
  if (score >= 50) return "medium";
  return "low";
}

export { computeListingMilestone } from "./milestone";
export {
  BASELINE_ACTIVE_LISTING_COUNT,
  STANDARD_STATUS_LISTING_TARGET,
} from "./constants";
