/**
 * Issue #157 — Mock shop-progress tracking (P1.6-5)
 */
import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import {
  BASELINE_ACTIVE_LISTING_COUNT,
  STANDARD_STATUS_LISTING_TARGET,
  clearShopProgress,
  computeListingMilestone,
  getReadinessScoreBucket,
  incrementActiveListingCount,
  loadShopProgress,
  recordExportCompleted,
  updateListingWidgetState,
  type ListingWidgetState,
} from "@/lib/workflows/new-seller/shop-progress";

const PERSONA: PersonaId = "new";

beforeEach(() => {
  sessionStorage.clear();
  clearShopProgress(PERSONA);
});

describe("Issue #157: listing milestone computation", () => {
  it("computes percent toward 10-listing Standard-status target", () => {
    const atBaseline = computeListingMilestone(BASELINE_ACTIVE_LISTING_COUNT);
    expect(atBaseline.count).toBe(3);
    expect(atBaseline.target).toBe(STANDARD_STATUS_LISTING_TARGET);
    expect(atBaseline.percent).toBe(30);

    const afterExport = computeListingMilestone(BASELINE_ACTIVE_LISTING_COUNT + 1);
    expect(afterExport.count).toBe(4);
    expect(afterExport.percent).toBe(40);
  });
});

describe("Issue #157: shop progress session persistence", () => {
  it("starts at baseline listing count and NoDistributor widget state", () => {
    const progress = loadShopProgress(PERSONA);
    expect(progress.activeListingCount).toBe(BASELINE_ACTIVE_LISTING_COUNT);
    expect(progress.widgetState).toBe("no_distributor");
  });

  it("persists widget state updates per persona across reloads", () => {
    updateListingWidgetState(PERSONA, "distributor_known");
    const reloaded = loadShopProgress(PERSONA);
    expect(reloaded.widgetState).toBe("distributor_known");
  });

  it("increments active listing count on export completion", () => {
    incrementActiveListingCount(PERSONA);
    expect(loadShopProgress(PERSONA).activeListingCount).toBe(4);
    incrementActiveListingCount(PERSONA);
    expect(loadShopProgress(PERSONA).activeListingCount).toBe(5);
  });

  it("recordExportCompleted sets Published-stub and increments count atomically", () => {
    recordExportCompleted(PERSONA);
    const progress = loadShopProgress(PERSONA);
    expect(progress.widgetState).toBe("published_stub");
    expect(progress.activeListingCount).toBe(4);
  });
});

describe("Issue #157: readiness score bucket", () => {
  it.each([
    [45, "low"],
    [69, "medium"],
    [70, "high"],
    [95, "high"],
  ] as const)("score %i maps to %s bucket", (score, bucket) => {
    expect(getReadinessScoreBucket(score)).toBe(bucket);
  });
});

describe("Issue #157: widget state enum coverage", () => {
  const states: ListingWidgetState[] = [
    "no_distributor",
    "distributor_known",
    "draft_generated",
    "published_stub",
  ];

  it("supports all four widget states", () => {
    for (const state of states) {
      updateListingWidgetState(PERSONA, state);
      expect(loadShopProgress(PERSONA).widgetState).toBe(state);
    }
  });
});
