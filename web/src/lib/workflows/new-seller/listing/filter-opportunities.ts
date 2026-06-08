import type { Opportunity } from "@/lib/mock-data/listing-workflow/schemas";
import type { OpportunityConstraints } from "./state-machine";

export function filterOpportunities(
  opportunities: Opportunity[],
  constraints: OpportunityConstraints,
): Opportunity[] {
  return opportunities
    .filter((item) => {
      if (constraints.category && item.category !== constraints.category) {
        return false;
      }
      if (item.min_capital_vnd > constraints.maxCapitalVnd) {
        return false;
      }
      if (constraints.dropshipOnly && !item.supports_dropship) {
        return false;
      }
      return true;
    })
    .sort((a, b) => a.opportunity_id.localeCompare(b.opportunity_id));
}
