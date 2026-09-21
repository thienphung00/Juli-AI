import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TIKTOK_EVENTS } from "../data-source";
import { relayTikTokEvent } from "../relay";
import { TIKTOK_RELAY_PATH } from "../relay-contract";

let sendBeacon: ReturnType<typeof vi.fn>;

/** jsdom's Blob has no `text()`; FileReader is what it does implement. */
function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error);
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(blob);
  });
}

async function beaconBody(): Promise<Record<string, unknown>> {
  const [, blob] = sendBeacon.mock.calls[0] as [string, Blob];

  return JSON.parse(await readBlob(blob)) as Record<string, unknown>;
}

beforeEach(() => {
  window.localStorage.clear();
  sendBeacon = vi.fn(() => true);
  Object.defineProperty(navigator, "sendBeacon", {
    configurable: true,
    value: sendBeacon,
    writable: true,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("relayTikTokEvent", () => {
  it("beacons the event to this origin's own relay route", async () => {
    relayTikTokEvent(TIKTOK_EVENTS.startDemo, "event-1", { content_name: "hero" }, {});

    expect(sendBeacon).toHaveBeenCalledWith(TIKTOK_RELAY_PATH, expect.any(Blob));
    await expect(beaconBody()).resolves.toMatchObject({
      event: "StartDemo",
      event_id: "event-1",
      properties: { content_name: "hero" },
    });
  });

  it("uses a beacon, not a fetch, so a click that navigates away still reports", () => {
    // A normal fetch is cancelled on unload, which is exactly when StartDemo
    // fires.
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    relayTikTokEvent(TIKTOK_EVENTS.startDemo, "event-1", {}, {});

    expect(sendBeacon).toHaveBeenCalledTimes(1);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("falls back to a keepalive fetch when the beacon is refused", () => {
    sendBeacon.mockReturnValue(false);
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 202 }));

    relayTikTokEvent(TIKTOK_EVENTS.startDemo, "event-1", {}, {});

    expect(fetchSpy).toHaveBeenCalledWith(
      TIKTOK_RELAY_PATH,
      expect.objectContaining({ keepalive: true, method: "POST" }),
    );
  });

  it("carries the click id and the hashed identifiers", async () => {
    window.localStorage.setItem("juli_tiktok_click_id", "click-1");

    relayTikTokEvent(TIKTOK_EVENTS.completeRegistration, "event-1", {}, {
      email: "a".repeat(64),
    });

    await expect(beaconBody()).resolves.toMatchObject({
      ttclid: "click-1",
      user: { email: "a".repeat(64) },
    });
  });

  it("sends no user key when nothing identifies the visitor", async () => {
    relayTikTokEvent(TIKTOK_EVENTS.viewContent, "event-1", {}, {});

    expect(await beaconBody()).not.toHaveProperty("user");
  });

  it("never sends an event time — the server sets that from its own clock", async () => {
    relayTikTokEvent(TIKTOK_EVENTS.viewContent, "event-1", {}, {});

    const body = await beaconBody();
    expect(body).not.toHaveProperty("event_time");
    expect(body).not.toHaveProperty("timestamp");
  });

  it("stays silent when the beacon throws", () => {
    sendBeacon.mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 202 }));

    expect(() =>
      relayTikTokEvent(TIKTOK_EVENTS.viewContent, "event-1", {}, {}),
    ).not.toThrow();
  });
});
