import {
  BASELINE_ACTIVE_LISTING_COUNT,
  STANDARD_STATUS_LISTING_TARGET,
} from "./constants";
import type { ListingMilestone } from "./types";

export function computeListingMilestone(
  activeListingCount: number = BASELINE_ACTIVE_LISTING_COUNT,
): ListingMilestone {
  const count = Math.max(0, activeListingCount);
  const target = STANDARD_STATUS_LISTING_TARGET;
  const percent = Math.min(Math.round((count / target) * 100), 100);
  const remaining = Math.max(target - count, 0);

  return { count, target, percent, remaining };
}
