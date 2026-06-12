/**
 * Issue #179 — useOperationsPipeline integration (P1.8-4)
 */
import { renderHook, waitFor } from "@testing-library/react";
import { useOperationsPipeline } from "@/lib/operations/use-operations-pipeline";
import { classifyShopProfile, computeHealthCheckResults } from "@/lib/operations";
import { rankWorkflowRecommendations } from "@/lib/operations/recommendations";
import {
  loadOperationalModelForPersona,
  VALIDATED_WORKFLOW_IDS,
} from "@/lib/mock-data/operations";
import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";

const PERSONA_PROFILE: Record<PersonaId, "NEW_SHOP" | "MID_LARGE_SHOP"> = {
  new: "NEW_SHOP",
  leakage: "MID_LARGE_SHOP",
  growth: "MID_LARGE_SHOP",
};

describe("Issue #179: useOperationsPipeline", () => {
  it("integration mock persona classify health rank envelope chain via hook", async () => {
    const personaId = "new" as const;
    const { result } = renderHook(() => useOperationsPipeline({ personaId }));

    await waitFor(() => {
      expect(result.current.status).toBe("ready");
    });

    const model = loadOperationalModelForPersona(personaId);
    const expectedProfile = classifyShopProfile(model);
    const expectedHealth = computeHealthCheckResults(model);
    const expectedRecommendations = rankWorkflowRecommendations(expectedProfile, expectedHealth);

    expect(result.current.personaId).toBe(personaId);
    expect(result.current.unifiedModel.shop_metadata.shop_id).toBe(
      model.shop_metadata.shop_id,
    );
    expect(result.current.shopProfile).toBe(expectedProfile);
    expect(result.current.shopProfile).toBe(PERSONA_PROFILE[personaId]);
    expect(result.current.healthResults).toEqual(expectedHealth);
    expect(result.current.workflowRecommendations).toEqual(expectedRecommendations);
  });

  it.each(["new", "leakage", "growth"] as const)(
    "loads persona %s → classify → health → rank envelope chain",
    async (personaId) => {
      const { result } = renderHook(() => useOperationsPipeline({ personaId }));

      await waitFor(() => {
        expect(result.current.status).toBe("ready");
      });

      const model = loadOperationalModelForPersona(personaId);
      const expectedProfile = classifyShopProfile(model);
      const expectedHealth = computeHealthCheckResults(model);
      const expectedRecommendations = rankWorkflowRecommendations(expectedProfile, expectedHealth);

      expect(result.current.personaId).toBe(personaId);
      expect(result.current.unifiedModel.shop_metadata.shop_id).toBe(
        model.shop_metadata.shop_id,
      );
      expect(result.current.shopProfile).toBe(expectedProfile);
      expect(result.current.shopProfile).toBe(PERSONA_PROFILE[personaId]);
      expect(result.current.healthResults).toEqual(expectedHealth);
      expect(result.current.workflowRecommendations).toEqual(expectedRecommendations);
    },
  );

  it("recomputes pipeline when personaId changes", async () => {
    const { result, rerender } = renderHook(
      ({ personaId }: { personaId: PersonaId }) => useOperationsPipeline({ personaId }),
      { initialProps: { personaId: "new" as PersonaId } },
    );

    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.shopProfile).toBe("NEW_SHOP");

    rerender({ personaId: "leakage" });

    await waitFor(() => expect(result.current.shopProfile).toBe("MID_LARGE_SHOP"));
    expect(result.current.personaId).toBe("leakage");
  });

  it("never surfaces workflow IDs outside the validated catalog", async () => {
    const { result } = renderHook(() => useOperationsPipeline({ personaId: "growth" }));

    await waitFor(() => expect(result.current.status).toBe("ready"));

    for (const item of result.current.workflowRecommendations.recommended_workflows) {
      expect(VALIDATED_WORKFLOW_IDS).toContain(item.workflow_id);
    }
  });
});
