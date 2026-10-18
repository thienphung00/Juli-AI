import { webcrypto } from "node:crypto";

import { sha256Hex } from "@juli/tiktok-events";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { adMeasurement, resetAdMeasurement } from "../privacy/ad-measurement";
import {
  REGISTERED_USERS_STORAGE_KEY,
  readSupabaseIdentity,
  reportTikTokRegistration,
} from "../tiktok-registration";

interface FakePixel {
  identify: ReturnType<typeof vi.fn>;
  page: ReturnType<typeof vi.fn>;
  track: ReturnType<typeof vi.fn>;
}

let pixel: FakePixel;

/** A GoTrue-shaped access token. Unsigned — nothing here verifies it, by design. */
function accessTokenFor(claims: Record<string, unknown>): string {
  const payload = Buffer.from(JSON.stringify(claims))
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");

  return `header.${payload}.signature`;
}

beforeAll(() => {
  // jsdom ships no SubtleCrypto; advanced matching needs a real digest.
  if (!globalThis.crypto?.subtle) {
    Object.defineProperty(globalThis, "crypto", { value: webcrypto });
  }
});

/** The Demo reports nothing for a visitor who did not arrive from an ad. */
function arriveFromAd(clickId = "click-1") {
  window.localStorage.setItem("juli_tiktok_click_id", clickId);
}

/** `GET /v1/me/privacy` for a seller with the given ad-measurement choice. */
function privacyResponse(adMeasurementOptOut: boolean): Response {
  return new Response(
    JSON.stringify({
      marketing_opt_out: false,
      ad_measurement_opt_out: adMeasurementOptOut,
      case_study_opt_in: false,
      terms_date_accepted: "2026-10-18",
      terms_accepted_at: null,
      liability_clause_accepted_at: null,
      current_terms_date: "2026-10-18",
      needs_terms_acceptance: false,
      deletion_scheduled_for: null,
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

let privacyFetch: ReturnType<typeof vi.fn>;

beforeEach(() => {
  window.localStorage.clear();
  resetAdMeasurement();
  // P50: every registration first reads the seller's privacy choice.
  privacyFetch = vi.fn(async () => privacyResponse(false));
  vi.stubGlobal("fetch", privacyFetch);
  arriveFromAd();
  // The server copy of every event goes out as a beacon; stub it so the suite
  // makes no network calls.
  Object.defineProperty(navigator, "sendBeacon", {
    configurable: true,
    value: vi.fn(() => true),
    writable: true,
  });
  pixel = { identify: vi.fn(), page: vi.fn(), track: vi.fn() };
  (window as unknown as { ttq?: FakePixel }).ttq = pixel;
});

afterEach(() => {
  delete (window as unknown as { ttq?: FakePixel }).ttq;
  vi.unstubAllGlobals();
});

describe("readSupabaseIdentity", () => {
  it("reads the email and subject claim", () => {
    const token = accessTokenFor({ email: "Seller@Example.com", sub: "user-1" });

    expect(readSupabaseIdentity(token)).toEqual({
      email: "Seller@Example.com",
      userId: "user-1",
    });
  });

  it("returns nulls for a token it cannot decode", () => {
    expect(readSupabaseIdentity("not-a-jwt")).toEqual({ email: null, userId: null });
  });

  it("ignores claims of the wrong type", () => {
    const token = accessTokenFor({ email: 42, sub: { nested: true } });

    expect(readSupabaseIdentity(token)).toEqual({ email: null, userId: null });
  });
});

describe("the ad-referral gate", () => {
  it("reports nothing for a visitor who did not arrive from a TikTok ad", async () => {
    // The pixel is never loaded for them either
    // (`components/tiktok-tracking.tsx`), but the gate has to be here too: a
    // tracked event also beacons a server copy, which would reach TikTok with
    // no pixel in the page and nothing in the browser to show for it.
    window.localStorage.clear();

    await reportTikTokRegistration(accessTokenFor({ email: "seller@example.com", sub: "user-1" }));

    expect(pixel.track).not.toHaveBeenCalled();
    expect(pixel.identify).not.toHaveBeenCalled();
  });

  it("reports for a visitor whose ad click was captured on an earlier visit", async () => {
    // The click id outlives the session precisely so a sign-up days later is
    // still attributed.
    window.localStorage.clear();
    arriveFromAd("click-from-last-week");

    await reportTikTokRegistration(accessTokenFor({ sub: "user-1" }));

    expect(pixel.track).toHaveBeenCalledTimes(1);
  });
});

describe("reportTikTokRegistration", () => {
  it("identifies the seller by hashed Juli user id only — never the (Google) email", async () => {
    const token = accessTokenFor({ email: "  Seller@Example.COM ", sub: "user-1" });

    await reportTikTokRegistration(token);

    expect(pixel.identify).toHaveBeenCalledWith({
      external_id: await sha256Hex("user-1"),
    });
    expect(pixel.track).toHaveBeenCalledWith(
      "CompleteRegistration",
      {},
      { event_id: expect.any(String) },
    );
    // Order matters: identify seeds the matching state the next event reads.
    expect(pixel.identify.mock.invocationCallOrder[0]).toBeLessThan(
      pixel.track.mock.invocationCallOrder[0],
    );
  });

  it("counts a seller once, not on every sign-in", async () => {
    // One Google callback serves signing up and signing back in, so without
    // this guard a returning seller reports a fresh conversion every visit.
    const token = accessTokenFor({ email: "seller@example.com", sub: "user-1" });

    await reportTikTokRegistration(token);
    await reportTikTokRegistration(token);
    await reportTikTokRegistration(token);

    expect(pixel.track).toHaveBeenCalledTimes(1);
  });

  it("counts a different seller on the same browser", async () => {
    await reportTikTokRegistration(accessTokenFor({ sub: "user-1" }));
    await reportTikTokRegistration(accessTokenFor({ sub: "user-2" }));

    expect(pixel.track).toHaveBeenCalledTimes(2);
  });

  it("records nothing for a token with no subject claim", async () => {
    await reportTikTokRegistration(accessTokenFor({ email: "seller@example.com" }));

    expect(pixel.track).not.toHaveBeenCalled();
    expect(pixel.identify).not.toHaveBeenCalled();
  });

  it("records the registration even when it cannot remember doing so", async () => {
    const setItem = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new Error("storage disabled");
      });

    await reportTikTokRegistration(accessTokenFor({ sub: "user-1" }));

    expect(pixel.track).toHaveBeenCalledTimes(1);
    setItem.mockRestore();
  });

  it("survives a corrupted storage record", async () => {
    window.localStorage.setItem(REGISTERED_USERS_STORAGE_KEY, "{not json");

    await reportTikTokRegistration(accessTokenFor({ sub: "user-1" }));

    expect(pixel.track).toHaveBeenCalledTimes(1);
  });

  it("still records when the pixel is blocked, so the event id exists for the server copy", async () => {
    delete (window as unknown as { ttq?: FakePixel }).ttq;

    await expect(
      reportTikTokRegistration(accessTokenFor({ sub: "user-1" })),
    ).resolves.toBeUndefined();
  });
});

describe("the seller's ad-measurement choice (P50, D60.6)", () => {
  it("reads GET /v1/me/privacy with the new session's token", async () => {
    const token = accessTokenFor({ sub: "user-1" });

    await reportTikTokRegistration(token);

    expect(privacyFetch).toHaveBeenCalledWith(
      "/v1/me/privacy",
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: `Bearer ${token}` }) }),
    );
  });

  it("sends no identify, no event and no server copy for a seller who opted out", async () => {
    privacyFetch.mockImplementation(async () => privacyResponse(true));
    const beacon = vi.fn(() => true);
    Object.defineProperty(navigator, "sendBeacon", { configurable: true, value: beacon, writable: true });

    await reportTikTokRegistration(accessTokenFor({ sub: "user-1" }));

    expect(pixel.identify).not.toHaveBeenCalled();
    expect(pixel.track).not.toHaveBeenCalled();
    expect(beacon).not.toHaveBeenCalled();
    expect(adMeasurement()).toBe("blocked");
  });

  it("does not count an opted-out sign-in, so nothing is claimed for later", async () => {
    privacyFetch.mockImplementation(async () => privacyResponse(true));

    await reportTikTokRegistration(accessTokenFor({ sub: "user-1" }));

    expect(window.localStorage.getItem(REGISTERED_USERS_STORAGE_KEY)).toBeNull();
  });

  it("sends nothing when the choice cannot be read", async () => {
    privacyFetch.mockImplementation(async () => new Response("{}", { status: 503 }));

    await reportTikTokRegistration(accessTokenFor({ sub: "user-1" }));

    expect(pixel.track).not.toHaveBeenCalled();
  });

  it("asks nothing for a visitor no ad sent", async () => {
    window.localStorage.clear();

    await reportTikTokRegistration(accessTokenFor({ sub: "user-1" }));

    expect(privacyFetch).not.toHaveBeenCalled();
  });
});
