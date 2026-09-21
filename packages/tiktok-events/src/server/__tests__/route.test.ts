// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createTikTokRelayRoute } from "../route";

let fetchImpl: ReturnType<typeof vi.fn>;

function relayRequest(
  body: unknown,
  headers: Record<string, string> = {},
): Request {
  const serialized = typeof body === "string" ? body : JSON.stringify(body);

  return new Request("https://app-juli.com/api/tt/event", {
    body: serialized,
    headers: {
      "Content-Type": "application/json",
      origin: "https://app-juli.com",
      ...headers,
    },
    method: "POST",
  });
}

function route() {
  return createTikTokRelayRoute({
    allowedOrigins: ["https://app-juli.com"],
    config: { accessToken: "token" },
    fetchImpl: fetchImpl as unknown as typeof fetch,
    onError: () => undefined,
  });
}

beforeEach(() => {
  fetchImpl = vi.fn(
    async () =>
      new Response(JSON.stringify({ code: 0 }), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      }),
  );
});

describe("the relay route", () => {
  it("accepts a well-formed event", async () => {
    const response = await route()(
      relayRequest({ event: "StartDemo", event_id: "event-1" }),
    );

    expect(response.status).toBe(202);
    await expect(response.json()).resolves.toEqual({ status: "accepted" });
  });

  it("refuses an oversized body without parsing it", async () => {
    const response = await route()(
      relayRequest({ event: "StartDemo", event_id: "event-1" }, {
        "content-length": "999999",
      }),
    );

    expect(response.status).toBe(413);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses a body that is not JSON", async () => {
    const response = await route()(relayRequest("{not json"));

    expect(response.status).toBe(400);
  });

  it("prefers X-Real-IP, which is the address nginx resolved", async () => {
    await route()(
      relayRequest({ event: "StartDemo", event_id: "event-1" }, {
        "x-forwarded-for": "198.51.100.1, 203.0.113.7",
        "x-real-ip": "203.0.113.9",
      }),
    );

    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string).data[0].user.ip).toBe("203.0.113.9");
  });

  it("falls back to the first X-Forwarded-For hop, never a later one", async () => {
    // Everything after the first entry is client-supplied.
    await route()(
      relayRequest({ event: "StartDemo", event_id: "event-1" }, {
        "x-forwarded-for": "198.51.100.1, 203.0.113.7",
      }),
    );

    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string).data[0].user.ip).toBe("198.51.100.1");
  });
});
