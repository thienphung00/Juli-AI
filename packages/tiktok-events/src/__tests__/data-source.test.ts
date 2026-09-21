import { describe, expect, it } from "vitest";

import {
  isTrackedEventName,
  TIKTOK_DATA_SOURCE_ID,
  TIKTOK_EVENTS,
  TRACKED_EVENT_NAMES,
} from "../data-source";

describe("the data source", () => {
  it("is the id configured in TikTok Events Manager", () => {
    expect(TIKTOK_DATA_SOURCE_ID).toBe("DAO9C6JC77U88MSNU74G");
  });
});

describe("isTrackedEventName", () => {
  it("accepts every event the apps send through track()", () => {
    for (const name of TRACKED_EVENT_NAMES) {
      expect(isTrackedEventName(name)).toBe(true);
    }
  });

  it("rejects Pageview, which the base code fires and track() never sends", () => {
    expect(isTrackedEventName(TIKTOK_EVENTS.pageView)).toBe(false);
  });

  it("rejects an arbitrary event name", () => {
    // The relay validates a public request body with this. An event name it
    // waves through is an event name anyone can write into the data source.
    expect(isTrackedEventName("Purchase")).toBe(false);
    expect(isTrackedEventName("")).toBe(false);
    expect(isTrackedEventName(null)).toBe(false);
    expect(isTrackedEventName({ toString: () => "ViewContent" })).toBe(false);
  });
});
