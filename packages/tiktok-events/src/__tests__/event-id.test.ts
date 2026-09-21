import { describe, expect, it } from "vitest";

import { newEventId } from "../event-id";

describe("newEventId", () => {
  it("mints a distinct id per call", () => {
    const ids = new Set(Array.from({ length: 500 }, () => newEventId()));

    expect(ids.size).toBe(500);
  });

  it("returns a non-empty string", () => {
    expect(newEventId().length).toBeGreaterThan(8);
  });
});
