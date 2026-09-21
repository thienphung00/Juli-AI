// @vitest-environment node
import { describe, expect, it } from "vitest";

import { TIKTOK_DATA_SOURCE_ID, TIKTOK_EVENTS } from "../../data-source";
import { buildTikTokEventPayload } from "../payload";

const baseEvent = {
  eventId: "event-1",
  eventName: TIKTOK_EVENTS.startDemo,
  eventTime: 1_700_000_000,
};

describe("buildTikTokEventPayload", () => {
  it("addresses the one data source as a web source", () => {
    const payload = buildTikTokEventPayload(baseEvent, {});

    expect(payload.event_source).toBe("web");
    expect(payload.event_source_id).toBe(TIKTOK_DATA_SOURCE_ID);
  });

  it("carries the event id the pixel used, which is what deduplicates the pair", () => {
    const payload = buildTikTokEventPayload(baseEvent, {});

    expect(payload.data).toHaveLength(1);
    expect(payload.data[0]).toMatchObject({
      event: "StartDemo",
      event_id: "event-1",
      event_time: 1_700_000_000,
    });
  });

  it("adds what only the server knows: address, user agent, pixel cookie", () => {
    const payload = buildTikTokEventPayload(baseEvent, {
      ip: "203.0.113.7",
      ttp: "ttp-cookie",
      userAgent: "Mozilla/5.0",
    });

    expect(payload.data[0].user).toEqual({
      ip: "203.0.113.7",
      ttp: "ttp-cookie",
      user_agent: "Mozilla/5.0",
    });
  });

  it("merges the click id and the hashed identifiers into the same user object", () => {
    const payload = buildTikTokEventPayload(
      { ...baseEvent, ttclid: "click-1", user: { email: "a".repeat(64) } },
      { ip: "203.0.113.7" },
    );

    expect(payload.data[0].user).toEqual({
      email: "a".repeat(64),
      ip: "203.0.113.7",
      ttclid: "click-1",
    });
  });

  it("omits page and properties entirely rather than sending empty objects", () => {
    const payload = buildTikTokEventPayload({ ...baseEvent, properties: {} }, {});

    expect(payload.data[0]).not.toHaveProperty("page");
    expect(payload.data[0]).not.toHaveProperty("properties");
  });

  it("sends a page with only the parts it has", () => {
    const payload = buildTikTokEventPayload(
      { ...baseEvent, pageUrl: "https://app-juli.com/" },
      {},
    );

    expect(payload.data[0].page).toEqual({ url: "https://app-juli.com/" });
  });

  it("includes the test event code only when one is configured", () => {
    expect(buildTikTokEventPayload(baseEvent, {})).not.toHaveProperty("test_event_code");
    expect(
      buildTikTokEventPayload(baseEvent, {}, { testEventCode: "TEST123" }),
    ).toMatchObject({ test_event_code: "TEST123" });
  });
});
