import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";

export const DEMO_PERSONA_STORAGE_KEY = "juli_demo_persona_id";

export const DEFAULT_PERSONA_ID: PersonaId = "new";

const PERSONA_IDS: PersonaId[] = ["new", "leakage", "growth"];

export function isPersonaId(value: string | null): value is PersonaId {
  return PERSONA_IDS.includes(value as PersonaId);
}

export function readStoredPersonaId(): PersonaId {
  if (typeof window === "undefined") return DEFAULT_PERSONA_ID;
  const stored = localStorage.getItem(DEMO_PERSONA_STORAGE_KEY);
  return isPersonaId(stored) ? stored : DEFAULT_PERSONA_ID;
}

export function persistPersonaId(id: PersonaId): void {
  localStorage.setItem(DEMO_PERSONA_STORAGE_KEY, id);
}
