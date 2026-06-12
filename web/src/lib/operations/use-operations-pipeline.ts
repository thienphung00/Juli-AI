"use client";

import { useMemo } from "react";
import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import { loadOperationalModelForPersona } from "@/lib/mock-data/operations";
import type { UnifiedOperationalDataModel } from "@/lib/mock-data/operations/schemas";

import { classifyShopProfile, type ShopProfileClassification } from "./classification";
import { computeHealthCheckResults, type HealthCheckResults } from "./health-check";
import {
  rankWorkflowRecommendations,
  type WorkflowRecommendations,
} from "./recommendations";

export type OperationsPipelineStatus = "ready";

export interface OperationsPipelineState {
  status: OperationsPipelineStatus;
  personaId: PersonaId;
  unifiedModel: UnifiedOperationalDataModel;
  shopProfile: ShopProfileClassification;
  healthResults: HealthCheckResults;
  workflowRecommendations: WorkflowRecommendations;
}

export function runOperationsPipeline(
  personaId: PersonaId,
): OperationsPipelineState {
  const unifiedModel = loadOperationalModelForPersona(personaId);
  const shopProfile = classifyShopProfile(unifiedModel);
  const healthResults = computeHealthCheckResults(unifiedModel);
  const workflowRecommendations = rankWorkflowRecommendations(shopProfile, healthResults);

  return {
    status: "ready",
    personaId,
    unifiedModel,
    shopProfile,
    healthResults,
    workflowRecommendations,
  };
}

/**
 * Orchestrates mock operations pipeline: load → classify → health → rank (P1.8-4).
 * Stable React hook API for downstream orchestration UI (#180+).
 */
export function useOperationsPipeline(options: {
  personaId: PersonaId;
}): OperationsPipelineState {
  const { personaId } = options;

  return useMemo(() => runOperationsPipeline(personaId), [personaId]);
}
