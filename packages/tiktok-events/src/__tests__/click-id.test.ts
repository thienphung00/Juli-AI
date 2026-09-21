import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  captureTikTokClickId,
  CLICK_ID_STORAGE_KEY,
  readTikTokClickId,
} from "../click-id";

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("captureTikTokClickId", () => {
  it("keeps the click id from the ad landing URL", () => {
    captureTikTokClickId("?ttclid=abc123&utm_source=tiktok");

    expect(readTikTokClickId()).toBe("abc123");
  });

  it("outlives the session, because the interval it measures can be weeks", () => {
    captureTikTokClickId("?ttclid=abc123");

    expect(window.localStorage.getItem(CLICK_ID_STORAGE_KEY)).toBe("abc123");
    expect(window.sessionStorage.getItem(CLICK_ID_STORAGE_KEY)).toBeNull();
  });

  it("leaves a previously captured id alone when a later page has no parameter", () => {
    captureTikTokClickId("?ttclid=abc123");
    captureTikTokClickId("?utm_source=newsletter");

    expect(readTikTokClickId()).toBe("abc123");
  });

  it("replaces the id when the visitor arrives from a different ad", () => {
    captureTikTokClickId("?ttclid=first");
    captureTikTokClickId("?ttclid=second");

    expect(readTikTokClickId()).toBe("second");
  });

  it("does not throw when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage disabled");
    });

    expect(() => captureTikTokClickId("?ttclid=abc123")).not.toThrow();
  });
});

describe("readTikTokClickId", () => {
  it("is undefined for a visitor who did not arrive from an ad", () => {
    expect(readTikTokClickId()).toBeUndefined();
  });
});
