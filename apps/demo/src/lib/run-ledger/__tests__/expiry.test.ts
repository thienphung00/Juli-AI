import { describe, expect, it } from "vitest";

import { resolveExpiryCountdown } from "../expiry";

describe("resolveExpiryCountdown", () => {
  it("computes hours and minutes remaining from a fixed clock, exactly matching expires_at - now", () => {
    const now = new Date("2026-08-25T10:00:00.000Z").getTime();
    const expiresAt = "2026-08-25T13:58:00.000Z"; // 3h58m ahead

    const result = resolveExpiryCountdown(expiresAt, now);

    expect(result).toEqual({ label: "3 giờ 58 phút", expired: false });
  });

  it("does not drift when now advances by exactly one minute — same server expiry, new label", () => {
    const expiresAt = "2026-08-25T13:58:00.000Z";
    const at1000 = resolveExpiryCountdown(expiresAt, new Date("2026-08-25T10:00:00.000Z").getTime());
    const at1001 = resolveExpiryCountdown(expiresAt, new Date("2026-08-25T10:01:00.000Z").getTime());

    expect(at1000.label).toBe("3 giờ 58 phút");
    expect(at1001.label).toBe("3 giờ 57 phút");
  });

  it("omits the hours segment once under one hour remaining", () => {
    const now = new Date("2026-08-25T10:00:00.000Z").getTime();
    const expiresAt = "2026-08-25T10:42:00.000Z";

    expect(resolveExpiryCountdown(expiresAt, now)).toEqual({
      label: "42 phút",
      expired: false,
    });
  });

  it("reports expired once the server expiry has passed, never a negative countdown", () => {
    const now = new Date("2026-08-25T14:00:00.000Z").getTime();
    const expiresAt = "2026-08-25T13:58:00.000Z";

    expect(resolveExpiryCountdown(expiresAt, now)).toEqual({
      label: "0 phút",
      expired: true,
    });
  });

  it("reports expired at the exact expiry instant", () => {
    const expiresAt = "2026-08-25T13:58:00.000Z";
    const now = new Date(expiresAt).getTime();

    expect(resolveExpiryCountdown(expiresAt, now).expired).toBe(true);
  });
});
