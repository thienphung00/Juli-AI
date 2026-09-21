// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  handleTikTokRelayRequest,
  resetTikTokRelayLogThrottle,
  type TikTokRelayRequest,
} from "../handler";
import type { TikTokEventsApiPayload } from "../payload";

const ALLOWED = ["https://app-juli.com"] as const;
const CONFIG = { accessToken: "token" };
const NOW = 1_700_000_000_000;

let fetchImpl: ReturnType<typeof vi.fn>;
let onError: ReturnType<typeof vi.fn>;

function sent(): TikTokEventsApiPayload {
  const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];

  return JSON.parse(init.body as string) as TikTokEventsApiPayload;
}

function post(overrides: Partial<TikTokRelayRequest> = {}, options = {}) {
  return handleTikTokRelayRequest(
    {
      body: { event: "StartDemo", event_id: "event-1" },
      origin: "https://app-juli.com",
      ...overrides,
    },
    {
      allowedOrigins: ALLOWED,
      config: CONFIG,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      now: () => NOW,
      onError,
      ...options,
    },
  );
}

beforeEach(() => {
  resetTikTokRelayLogThrottle();
  onError = vi.fn();
  fetchImpl = vi.fn(
    async () =>
      new Response(JSON.stringify({ code: 0 }), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      }),
  );
});

describe("who may post", () => {
  it("accepts a page we serve", async () => {
    await expect(post()).resolves.toMatchObject({ status: 202 });
  });

  it("accepts a beacon that carries only a Referer", async () => {
    // Not every browser sends Origin on a sendBeacon POST.
    await expect(
      post({ origin: null, referer: "https://app-juli.com/?ttclid=x" }),
    ).resolves.toMatchObject({ status: 202 });
  });

  it("refuses another site's page", async () => {
    await expect(post({ origin: "https://evil.example" })).resolves.toMatchObject({
      status: 403,
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses a request that names no origin at all", async () => {
    await expect(post({ origin: null, referer: null })).resolves.toMatchObject({
      status: 403,
    });
  });

  it("refuses an origin that merely contains an allowed one", async () => {
    await expect(
      post({ origin: "https://app-juli.com.evil.example" }),
    ).resolves.toMatchObject({ status: 403 });
  });
});

describe("what may be posted", () => {
  it("refuses an event name outside the allowlist", async () => {
    // The endpoint is unauthenticated; the allowlist is what stops it being a
    // way to write arbitrary events into the data source.
    for (const event of ["Purchase", "Pageview", "", null, 42]) {
      await expect(post({ body: { event, event_id: "event-1" } })).resolves.toMatchObject({
        status: 400,
      });
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses a missing or malformed event id", async () => {
    for (const eventId of [undefined, "", "a".repeat(129), "has spaces", "<script>"]) {
      await expect(
        post({ body: { event: "StartDemo", event_id: eventId } }),
      ).resolves.toMatchObject({ status: 400 });
    }
  });

  it("refuses a body that is not an object", async () => {
    await expect(post({ body: "StartDemo" })).resolves.toMatchObject({ status: 400 });
    await expect(post({ body: null })).resolves.toMatchObject({ status: 400 });
  });

  it("forwards only the properties it recognises", async () => {
    await post({
      body: {
        event: "StartDemo",
        event_id: "event-1",
        properties: {
          content_name: "hero-demo-cta",
          currency: "VND",
          injected: "<script>",
          value: 12,
        },
      },
    });

    expect(sent().data[0].properties).toEqual({
      content_name: "hero-demo-cta",
      currency: "VND",
      value: 12,
    });
  });

  it("drops a property of the wrong shape rather than forwarding it", async () => {
    await post({
      body: {
        event: "StartDemo",
        event_id: "event-1",
        properties: { currency: "dong", value: -5 },
      },
    });

    expect(sent().data[0]).not.toHaveProperty("properties");
  });

  it("forwards identifiers only when they are actually digests", async () => {
    await post({
      body: {
        event: "CompleteRegistration",
        event_id: "event-1",
        user: { email: "seller@example.com", external_id: "b".repeat(64) },
      },
    });

    // A raw address must never reach TikTok through this path, even if some
    // future caller sends one.
    expect(sent().data[0].user).toEqual({ external_id: "b".repeat(64) });
  });

  it("refuses a page_url from another origin", async () => {
    await post({
      body: {
        event: "StartDemo",
        event_id: "event-1",
        page_url: "https://evil.example/landing",
      },
    });

    expect(sent().data[0]).not.toHaveProperty("page");
  });

  it("keeps a referrer from anywhere, because that is what a referrer is", async () => {
    await post({
      body: {
        event: "StartDemo",
        event_id: "event-1",
        referrer: "https://www.tiktok.com/",
      },
    });

    expect(sent().data[0].page).toEqual({ referrer: "https://www.tiktok.com/" });
  });
});

describe("what the server adds", () => {
  it("times the event by its own clock, ignoring anything the client sent", async () => {
    await post({
      body: { event: "StartDemo", event_id: "event-1", event_time: 1 },
    });

    expect(sent().data[0].event_time).toBe(Math.floor(NOW / 1000));
  });

  it("attaches the address, user agent and the pixel's own cookie", async () => {
    await post({
      cookieHeader: "_ttp=ttp-value; other=ignored",
      ip: "203.0.113.7",
      userAgent: "Mozilla/5.0",
    });

    expect(sent().data[0].user).toMatchObject({
      ip: "203.0.113.7",
      ttp: "ttp-value",
      user_agent: "Mozilla/5.0",
    });
  });

  it("copes with a cookie header that has no _ttp", async () => {
    await post({ cookieHeader: "session=abc" });

    expect(sent().data[0].user).not.toHaveProperty("ttp");
  });
});

describe("when it cannot deliver", () => {
  it("fails loudly and visibly with no token, rather than quietly dropping events", async () => {
    const response = await post({}, { config: null });

    expect(response.status).toBe(503);
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith(
      expect.stringContaining("TIKTOK_EVENTS_API_ACCESS_TOKEN is not set"),
    );
  });

  it("logs the missing token once a minute, not once a visitor", async () => {
    await post({}, { config: null });
    await post({}, { config: null });
    await post({}, { config: null });

    expect(onError).toHaveBeenCalledTimes(1);
  });

  it("reports a TikTok rejection as a 502 and names the reason in the log", async () => {
    fetchImpl.mockResolvedValue(
      new Response(JSON.stringify({ code: 40002, message: "param error" }), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      }),
    );

    await expect(post()).resolves.toMatchObject({ status: 502 });
    expect(onError).toHaveBeenCalledWith(expect.stringContaining("param error"));
  });
});
