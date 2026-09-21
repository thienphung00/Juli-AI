// @vitest-environment node
import { describe, expect, it } from "vitest";

import {
  hashIdentity,
  normalizeEmail,
  normalizeExternalId,
  sha256Hex,
} from "../identity";

describe("normalizeEmail", () => {
  it("lowercases and trims, which is what TikTok hashes", () => {
    expect(normalizeEmail("  Seller@Example.COM \n")).toBe(
      "seller@example.com",
    );
  });

  it("rejects anything that is not plausibly an address", () => {
    // A placeholder that slipped through would be hashed and sent as a real
    // identifier, matching nobody while looking like coverage.
    for (const value of [
      "",
      "   ",
      "seller",
      "@example.com",
      "seller@",
      "seller@example",
      "seller@example.",
      null,
      undefined,
      42 as unknown as string,
    ]) {
      expect(normalizeEmail(value as string)).toBeNull();
    }
  });
});

describe("normalizeExternalId", () => {
  it("trims but preserves case", () => {
    // Supabase user ids are opaque; lowercasing one would destroy information.
    expect(normalizeExternalId("  A1b2-C3d4  ")).toBe("A1b2-C3d4");
  });

  it("rejects an empty or missing id", () => {
    expect(normalizeExternalId("   ")).toBeNull();
    expect(normalizeExternalId(null)).toBeNull();
  });
});

describe("sha256Hex", () => {
  it("matches the published SHA-256 vector for \"abc\"", () => {
    return expect(sha256Hex("abc")).resolves.toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });

  it("returns lowercase hex of the full digest", async () => {
    const digest = await sha256Hex("seller@example.com");

    expect(digest).toMatch(/^[0-9a-f]{64}$/);
  });
});

describe("hashIdentity", () => {
  it("hashes the normalised value, not the raw one", async () => {
    const fromRaw = await hashIdentity({ email: "  Seller@Example.COM " });
    const fromNormalized = await hashIdentity({ email: "seller@example.com" });

    // This equality is the whole point: the browser and the server normalise
    // through these same functions, so they cannot derive different digests
    // from the same person.
    expect(fromRaw.email).toBe(fromNormalized.email);
    expect(fromRaw.email).toBe(await sha256Hex("seller@example.com"));
  });

  it("omits a field it cannot normalise rather than sending an empty string", async () => {
    const hashed = await hashIdentity({ email: "not-an-address", externalId: "  " });

    expect(hashed).toEqual({});
    expect("email" in hashed).toBe(false);
    expect("external_id" in hashed).toBe(false);
  });

  it("carries both identifiers when both are present", async () => {
    const hashed = await hashIdentity({
      email: "seller@example.com",
      externalId: "sub-123",
    });

    expect(hashed.email).toMatch(/^[0-9a-f]{64}$/);
    expect(hashed.external_id).toBe(await sha256Hex("sub-123"));
  });
});
