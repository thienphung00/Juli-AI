import { GROWTH_PERSONA } from "./fixtures/growth-persona";
import { LEAKAGE_PERSONA } from "./fixtures/leakage-persona";
import { NEW_PERSONA } from "./fixtures/new-persona";
export { FORBIDDEN_PII_KEYS } from "./pii";
export type {
  MockAdCampaign,
  MockAffiliateEvent,
  MockOrder,
  MockReturn,
  MockTask,
  PersonaId,
  SellerPersona,
  SellerProfile,
  WorkflowId,
} from "./schemas";
export { validatePersona } from "./validate";
export type { ValidationResult } from "./validate";

import type { PersonaId, SellerPersona } from "./schemas";

const PERSONAS: Record<PersonaId, SellerPersona> = {
  new: NEW_PERSONA,
  leakage: LEAKAGE_PERSONA,
  growth: GROWTH_PERSONA,
};

export function listPersonaIds(): PersonaId[] {
  return Object.keys(PERSONAS) as PersonaId[];
}

export function loadPersona(id: PersonaId): SellerPersona {
  const persona = PERSONAS[id];
  if (!persona) {
    throw new Error(`Unknown persona: ${id}`);
  }
  return persona;
}
