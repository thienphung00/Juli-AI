import { webcrypto } from "node:crypto";

import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { TIKTOK_EVENTS } from "../data-source";
import { sha256Hex } from "../identity";
import { TIKTOK_RELAY_PATH } from "../relay-contract";
import {
  identifyTikTokUser,
  resetTikTokIdentity,
  trackTikTokEvent,
  trackTikTokPageView,
} from "../track";

interface FakePixel {
  identify: ReturnType<typeof vi.fn>;
  page: ReturnType<typeof vi.fn>;
  track: ReturnType<typeof vi.fn>;
}

function installPixel(overrides: Partial<FakePixel> = {}): FakePixel {
  const pixel: FakePixel = {
    identify: vi.fn(),
    page: vi.fn(),
    track: vi.fn(),
    ...overrides,
  };

  (window as unknown as { ttq?: FakePixel }).ttq = pixel;

  return pixel;
}

beforeAll(() => {
  // jsdom ships no SubtleCrypto. Advanced matching needs a real digest, and
  // the product code correctly degrades to "no identifiers" without one — so
  // supply Node's to test the path that matters.
  if (!globalThis.crypto?.subtle) {
    Object.defineProperty(globalThis, "crypto", { value: webcrypto });
  }
});

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

async function relayedBodies(): Promise<Array<Record<string, unknown>>> {
  return Promise.all(
    sendBeacon.mock.calls.map(async ([, blob]) =>
      JSON.parse(await readBlob(blob as Blob)),
    ),
  );
}

beforeEach(() => {
  delete (window as unknown as { ttq?: FakePixel }).ttq;
  resetTikTokIdentity();
  window.localStorage.clear();
  // Both channels fire on every track(); stub the second so the suite makes no
  // network calls.
  sendBeacon = vi.fn(() => true);
  Object.defineProperty(navigator, "sendBeacon", {
    configurable: true,
    value: sendBeacon,
    writable: true,
  });
});

describe("trackTikTokEvent", () => {
  it("sends the event with the id it returns", () => {
    const pixel = installPixel();

    const eventId = trackTikTokEvent(TIKTOK_EVENTS.startDemo);

    expect(pixel.track).toHaveBeenCalledWith(
      "StartDemo",
      {},
      { event_id: eventId },
    );
  });

  it("forwards properties untouched", () => {
    const pixel = installPixel();

    trackTikTokEvent(TIKTOK_EVENTS.viewContent, {
      content_name: "landing",
      content_type: "product",
    });

    expect(pixel.track).toHaveBeenCalledWith(
      "ViewContent",
      { content_name: "landing", content_type: "product" },
      { event_id: expect.any(String) },
    );
  });

  it("mints a fresh id per call", () => {
    installPixel();

    expect(trackTikTokEvent(TIKTOK_EVENTS.startDemo)).not.toBe(
      trackTikTokEvent(TIKTOK_EVENTS.startDemo),
    );
  });

  it("still returns an id when the pixel never loaded", () => {
    // A blocked pixel is exactly when the server-side copy is the only one
    // that arrives — and it needs this id to deduplicate against.
    const eventId = trackTikTokEvent(TIKTOK_EVENTS.startDemo);

    expect(eventId).toMatch(/\S/);
  });

  it("sends the server copy under the same id, which is what deduplicates them", async () => {
    const pixel = installPixel();

    const eventId = trackTikTokEvent(TIKTOK_EVENTS.startDemo, {
      content_name: "hero-demo-cta",
    });

    // TikTok collapses a pixel event and an Events API event sharing a name
    // and an event_id into one conversion. Different ids here would double
    // every number in the report.
    const [pixelCall] = pixel.track.mock.calls;
    expect((pixelCall[2] as { event_id: string }).event_id).toBe(eventId);
    await expect(relayedBodies()).resolves.toEqual([
      expect.objectContaining({
        event: "StartDemo",
        event_id: eventId,
        properties: { content_name: "hero-demo-cta" },
      }),
    ]);
  });

  it("still relays to the server when the pixel never loaded", async () => {
    const eventId = trackTikTokEvent(TIKTOK_EVENTS.startDemo);

    await expect(relayedBodies()).resolves.toEqual([
      expect.objectContaining({ event_id: eventId }),
    ]);
  });

  it("does not throw when a half-initialised pixel throws", () => {
    installPixel({
      track: vi.fn(() => {
        throw new Error("blocked by extension");
      }),
    });

    expect(() => trackTikTokEvent(TIKTOK_EVENTS.startDemo)).not.toThrow();
  });
});

describe("trackTikTokPageView", () => {
  it("fires a pageview for a client-side route change", () => {
    const pixel = installPixel();

    trackTikTokPageView();

    expect(pixel.page).toHaveBeenCalledTimes(1);
  });

  it("is a no-op without a pixel", () => {
    expect(() => trackTikTokPageView()).not.toThrow();
  });
});

describe("identifyTikTokUser", () => {
  it("passes hashed identifiers, never the raw values", async () => {
    const pixel = installPixel();

    await identifyTikTokUser({
      email: "  Seller@Example.COM ",
      externalId: "sub-123",
    });

    expect(pixel.identify).toHaveBeenCalledWith({
      email: await sha256Hex("seller@example.com"),
      external_id: await sha256Hex("sub-123"),
    });
  });

  it("carries the identifiers into later server copies too", async () => {
    installPixel();

    await identifyTikTokUser({ email: "seller@example.com" });
    trackTikTokEvent(TIKTOK_EVENTS.completeRegistration);

    await expect(relayedBodies()).resolves.toEqual([
      expect.objectContaining({
        user: { email: await sha256Hex("seller@example.com") },
      }),
    ]);
  });

  it("does not call identify when nothing normalises", async () => {
    const pixel = installPixel();

    await identifyTikTokUser({ email: "not-an-address", externalId: null });

    expect(pixel.identify).not.toHaveBeenCalled();
  });
});
