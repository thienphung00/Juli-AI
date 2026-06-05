import type { MockTask } from "@/lib/mock-data/seller-personas/schemas";

/** Rank growth tasks by estimated opportunity (impact VND), highest first. */
export function rankGrowthTasks(tasks: MockTask[]): MockTask[] {
  return [...tasks].sort((a, b) => {
    const impactA = a.estimated_impact_vnd ?? 0;
    const impactB = b.estimated_impact_vnd ?? 0;
    return impactB - impactA;
  });
}
