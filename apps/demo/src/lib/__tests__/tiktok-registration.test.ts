import { webcrypto } from "node:crypto";

import { sha256Hex } from "@juli/tiktok-events";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

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

beforeEach(() => {
  window.localStorage.clear();
  pixel = { identify: vi.fn(), page: vi.fn(), track: vi.fn() };
  (window as unknown as { ttq?: FakePixel }).ttq = pixel;
});

afterEach(() => {
  delete (window as unknown as { ttq?: FakePixel }).ttq;
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

describe("reportTikTokRegistration", () => {
  it("identifies the seller with hashed values, then records the registration", async () => {
    const token = accessTokenFor({ email: "  Seller@Example.COM ", sub: "user-1" });

    await reportTikTokRegistration(token);

    expect(pixel.identify).toHaveBeenCalledWith({
      email: await sha256Hex("seller@example.com"),
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
