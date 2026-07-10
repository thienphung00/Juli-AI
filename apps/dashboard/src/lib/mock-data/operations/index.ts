import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";

import {
  MID_LARGE_SHOP_GROWTH_BINDING,
  MID_LARGE_SHOP_OPERATIONAL_MODEL,
} from "./fixtures/mid-large-shop";
import { NEW_SHOP_OPERATIONAL_MODEL } from "./fixtures/new-shop";
import type { OperationalProfileId, ShopProfileType, UnifiedOperationalDataModel } from "./schemas";

export { VALIDATED_WORKFLOW_IDS } from "./schemas";
export type {
  AdCampaignPerformance,
  HealthDataSource,
  InventoryRecord,
  OperationalProfileId,
  ProbationData,
  ProductPerformance,
  ReturnsRefundsData,
  ShopMetadata,
  ShopProfileType,
  UnifiedOperationalDataModel,
  ValidatedWorkflowId,
  ViolationRecord,
} from "./schemas";
export {
  assertNoDatumsOutsideSignalRequirements,
  checkTraceability,
  collectModelDatumKeys,
  DATUM_TRACEABILITY_MAP,
  exportTraceabilityArtifact,
  getWorkflowsForDatum,
  listTraceabilityDatumKeys,
} from "./traceability";
export type { TraceabilityCheckResult } from "./traceability";
export {
  isValidatedWorkflowId,
  validateOperationalFixtures,
  validateUnifiedOperationalModel,
} from "./validate";
export type { ValidationResult } from "./validate";

import { validateOperationalFixtures } from "./validate";

const PROFILE_FIXTURES: Record<ShopProfileType, UnifiedOperationalDataModel> = {
  NEW_SHOP: NEW_SHOP_OPERATIONAL_MODEL,
  MID_LARGE_SHOP: MID_LARGE_SHOP_OPERATIONAL_MODEL,
};

const PERSONA_PROFILE_MAP: Record<PersonaId, ShopProfileType> = {
  new: "NEW_SHOP",
  leakage: "MID_LARGE_SHOP",
  growth: "MID_LARGE_SHOP",
};

/** Demo persona → shop profile mapping for PersonaSwitcher binding. */
export function resolveOperationalProfileForPersona(personaId: PersonaId): ShopProfileType {
  return PERSONA_PROFILE_MAP[personaId];
}

export function listOperationalProfiles(): OperationalProfileId[] {
  return ["NEW_SHOP", "MID_LARGE_SHOP"];
}

export function loadOperationalModel(profile: ShopProfileType): UnifiedOperationalDataModel {
  const model = PROFILE_FIXTURES[profile];
  if (!model) {
    throw new Error(`Unknown operational profile: ${profile}`);
  }
  return model;
}

/**
 * Loads the unified operational envelope for a demo persona.
 * Growth persona receives a MID_LARGE_SHOP variant with growth shop metadata.
 */
export function loadOperationalModelForPersona(personaId: PersonaId): UnifiedOperationalDataModel {
  if (personaId === "growth") {
    return MID_LARGE_SHOP_GROWTH_BINDING;
  }
  if (personaId === "leakage") {
    return MID_LARGE_SHOP_OPERATIONAL_MODEL;
  }
  return NEW_SHOP_OPERATIONAL_MODEL;
}

export function loadAllOperationalFixtures(): UnifiedOperationalDataModel[] {
  return [NEW_SHOP_OPERATIONAL_MODEL, MID_LARGE_SHOP_OPERATIONAL_MODEL];
}

export function validateOperationsFixtures() {
  return validateOperationalFixtures(loadAllOperationalFixtures());
}
