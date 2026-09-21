// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { TIKTOK_EVENTS } from "../../data-source";
import { buildTikTokEventPayload } from "../payload";
import { postTikTokEvent, TIKTOK_EVENTS_API_URL } from "../client";

const payload = buildTikTokEventPayload(
  { eventId: "event-1", eventName: TIKTOK_EVENTS.startDemo, eventTime: 1_700_000_000 },
  {},
);

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

describe("postTikTokEvent", () => {
  it("posts to the consolidated endpoint with the token in Access-Token", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ code: 0, message: "OK" }));

    await postTikTokEvent(payload, "secret-token", fetchImpl as unknown as typeof fetch);

    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(TIKTOK_EVENTS_API_URL);
    expect((init.headers as Record<string, string>)["Access-Token"]).toBe("secret-token");
    expect(JSON.parse(init.body as string)).toEqual(payload);
  });

  it("succeeds only on code 0", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ code: 0, message: "OK" }));

    await expect(
      postTikTokEvent(payload, "token", fetchImpl as unknown as typeof fetch),
    ).resolves.toEqual({ ok: true });
  });

  it("treats a 200 with a non-zero code as the failure it is", async () => {
    // TikTok answers HTTP 200 for a rejected event. Trusting response.ok here
    // is how a dashboard shows green while no conversion ever lands.
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ code: 40002, message: "param error: event_source_id" }),
    );

    await expect(
      postTikTokEvent(payload, "token", fetchImpl as unknown as typeof fetch),
    ).resolves.toEqual({
      code: 40002,
      ok: false,
      reason: "param error: event_source_id",
    });
  });

  it("reports a non-2xx response", async () => {
    const fetchImpl = vi.fn(async () => new Response("nope", { status: 401 }));

    await expect(
      postTikTokEvent(payload, "token", fetchImpl as unknown as typeof fetch),
    ).resolves.toEqual({ ok: false, reason: "HTTP 401" });
  });

  it("reports an unparseable body rather than throwing", async () => {
    const fetchImpl = vi.fn(async () => new Response("<html>", { status: 200 }));

    await expect(
      postTikTokEvent(payload, "token", fetchImpl as unknown as typeof fetch),
    ).resolves.toEqual({ ok: false, reason: "unparseable response body" });
  });

  it("reports a network failure rather than throwing", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });

    await expect(
      postTikTokEvent(payload, "token", fetchImpl as unknown as typeof fetch),
    ).resolves.toEqual({ ok: false, reason: "TypeError" });
  });
});
