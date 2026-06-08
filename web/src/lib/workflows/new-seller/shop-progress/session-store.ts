import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import {
  BASELINE_ACTIVE_LISTING_COUNT,
  SHOP_PROGRESS_SESSION_PREFIX,
  SHOP_PROGRESS_UPDATED_EVENT,
} from "./constants";
import type { ShopProgressSession } from "./types";

export function shopProgressStorageKey(personaId: PersonaId): string {
  return `${SHOP_PROGRESS_SESSION_PREFIX}${personaId}`;
}

export function createDefaultShopProgress(personaId: PersonaId): ShopProgressSession {
  return {
    version: 1,
    personaId,
    activeListingCount: BASELINE_ACTIVE_LISTING_COUNT,
    widgetState: "no_distributor",
  };
}

export function loadShopProgressSession(personaId: PersonaId): ShopProgressSession {
  if (typeof window === "undefined") {
    return createDefaultShopProgress(personaId);
  }

  try {
    const raw = sessionStorage.getItem(shopProgressStorageKey(personaId));
    if (!raw) return createDefaultShopProgress(personaId);

    const parsed = JSON.parse(raw) as ShopProgressSession;
    if (
      parsed?.version !== 1 ||
      parsed.personaId !== personaId ||
      typeof parsed.activeListingCount !== "number" ||
      typeof parsed.widgetState !== "string"
    ) {
      return createDefaultShopProgress(personaId);
    }

    return parsed;
  } catch {
    return createDefaultShopProgress(personaId);
  }
}

export function saveShopProgressSession(session: ShopProgressSession): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(
    shopProgressStorageKey(session.personaId),
    JSON.stringify(session),
  );
}

export function clearShopProgressSession(personaId: PersonaId): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(shopProgressStorageKey(personaId));
}

export function notifyShopProgressUpdated(personaId: PersonaId): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent(SHOP_PROGRESS_UPDATED_EVENT, { detail: { personaId } }),
  );
}
