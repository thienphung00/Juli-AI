import type { ShopProfileType, ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";

/**
 * ADR-013 Appendix A — profile-gated validated workflow catalog.
 * Ranking and recommendations must only surface IDs from this map.
 */
export const WORKFLOW_CATALOG: Readonly<
  Record<ShopProfileType, readonly ValidatedWorkflowId[]>
> = {
  NEW_SHOP: ["npl", "minimize_violations"],
  MID_LARGE_SHOP: [
    "budget_optimization",
    "product_scaling",
    "refund_spike_detection",
    "stockout_prevention",
  ],
};

export function getWorkflowsForProfile(
  profile: ShopProfileType,
): readonly ValidatedWorkflowId[] {
  return WORKFLOW_CATALOG[profile];
}
