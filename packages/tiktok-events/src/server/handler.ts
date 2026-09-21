import { isTrackedEventName, type TikTokEventProperties } from "../data-source";
import type { TikTokHashedIdentity } from "../identity";
import type { TikTokRelayEventBody } from "../relay-contract";
import { postTikTokEvent, type TikTokDeliveryResult } from "./client";
import { readTikTokServerConfig, type TikTokServerConfig } from "./config";
import { buildTikTokEventPayload } from "./payload";

const MAX_EVENT_ID_LENGTH = 128;
const MAX_URL_LENGTH = 2048;
const MAX_CLICK_ID_LENGTH = 512;
const MAX_TEXT_LENGTH = 200;
const SHA256_HEX = /^[0-9a-f]{64}$/;
const EVENT_ID = /^[A-Za-z0-9_-]{1,128}$/;
const CLICK_ID = /^[A-Za-z0-9._-]+$/;
const CURRENCY = /^[A-Z]{3}$/;

export interface TikTokRelayRequest {
  body: unknown;
  cookieHeader?: string | null;
  /** The true client address, already resolved by the edge. */
  ip?: string | null;
  origin?: string | null;
  referer?: string | null;
  userAgent?: string | null;
}

export interface TikTokRelayOptions {
  /** Origins whose pages are allowed to post here — this app's own, and no others. */
  allowedOrigins: readonly string[];
  config?: TikTokServerConfig | null;
  fetchImpl?: typeof fetch;
  now?: () => number;
  onError?: (message: string) => void;
}

export interface TikTokRelayResponse {
  body: { reason?: string; status: string };
  status: number;
}

function originOf(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }

  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

/**
 * Whether this request came from a page we serve.
 *
 * Be clear about what this does and does not buy. It stops another website's
 * JavaScript from writing events into our data source, which is the realistic
 * browser-side abuse. It does NOT stop a script that sets the header itself —
 * an anonymous visitor's pageview cannot be authenticated, so nothing here
 * can. What actually bounds that is the event-name allowlist and the strict
 * schema below (nothing but our four events, in our shape, can be injected)
 * plus the per-IP rate limit at nginx.
 */
function isAllowedOrigin(
  request: TikTokRelayRequest,
  allowedOrigins: readonly string[],
): boolean {
  const origin = originOf(request.origin) ?? originOf(request.referer);

  return origin !== null && allowedOrigins.includes(origin);
}

function readCookie(cookieHeader: string | null | undefined, name: string): string | undefined {
  if (!cookieHeader) {
    return undefined;
  }

  for (const part of cookieHeader.split(";")) {
    const separator = part.indexOf("=");

    if (separator < 0) {
      continue;
    }

    if (part.slice(0, separator).trim() === name) {
      return decodeURIComponent(part.slice(separator + 1).trim()) || undefined;
    }
  }

  return undefined;
}

function sanitizeText(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 && value.length <= MAX_TEXT_LENGTH
    ? value
    : undefined;
}

function sanitizeUrl(value: unknown, allowedOrigins?: readonly string[]): string | undefined {
  if (typeof value !== "string" || value.length === 0 || value.length > MAX_URL_LENGTH) {
    return undefined;
  }

  const origin = originOf(value);

  if (origin === null) {
    return undefined;
  }

  // For `page_url`, an origin check stops an arbitrary URL being laundered
  // into the report under our data source. A referrer legitimately points
  // anywhere — that is the point of it — so it is not constrained.
  return !allowedOrigins || allowedOrigins.includes(origin) ? value : undefined;
}

function sanitizeProperties(value: unknown): TikTokEventProperties {
  if (typeof value !== "object" || value === null) {
    return {};
  }

  const raw = value as Record<string, unknown>;
  const properties: TikTokEventProperties = {};

  // An allowlist, not a filter of known-bad keys: whatever is not named here
  // does not reach TikTok, so a new field cannot arrive without a code change.
  for (const key of ["content_id", "content_name", "content_type", "description"] as const) {
    const text = sanitizeText(raw[key]);
    if (text) {
      properties[key] = text;
    }
  }

  if (typeof raw.currency === "string" && CURRENCY.test(raw.currency)) {
    properties.currency = raw.currency;
  }

  if (typeof raw.value === "number" && Number.isFinite(raw.value) && raw.value >= 0) {
    properties.value = raw.value;
  }

  return properties;
}

/**
 * Keep only values that are actually SHA-256 digests. Anything else is a bug
 * on our side or a probe from someone else's; either way it is dropped rather
 * than forwarded, so a raw address can never reach TikTok through this path
 * even if a future caller sends one.
 */
function sanitizeUser(value: unknown): TikTokHashedIdentity {
  if (typeof value !== "object" || value === null) {
    return {};
  }

  const raw = value as Record<string, unknown>;
  const user: TikTokHashedIdentity = {};

  if (typeof raw.email === "string" && SHA256_HEX.test(raw.email)) {
    user.email = raw.email;
  }

  if (typeof raw.external_id === "string" && SHA256_HEX.test(raw.external_id)) {
    user.external_id = raw.external_id;
  }

  return user;
}

interface ParsedBody {
  body: TikTokRelayEventBody;
  ok: true;
}

function parseBody(value: unknown): ParsedBody | { ok: false; reason: string } {
  if (typeof value !== "object" || value === null) {
    return { ok: false, reason: "body must be an object" };
  }

  const raw = value as Record<string, unknown>;

  if (!isTrackedEventName(raw.event)) {
    return { ok: false, reason: "unknown event" };
  }

  if (
    typeof raw.event_id !== "string" ||
    raw.event_id.length > MAX_EVENT_ID_LENGTH ||
    !EVENT_ID.test(raw.event_id)
  ) {
    return { ok: false, reason: "invalid event_id" };
  }

  const body: TikTokRelayEventBody = {
    event: raw.event,
    event_id: raw.event_id,
  };

  const properties = sanitizeProperties(raw.properties);
  if (Object.keys(properties).length > 0) {
    body.properties = properties;
  }

  const user = sanitizeUser(raw.user);
  if (Object.keys(user).length > 0) {
    body.user = user;
  }

  if (
    typeof raw.ttclid === "string" &&
    raw.ttclid.length > 0 &&
    raw.ttclid.length <= MAX_CLICK_ID_LENGTH &&
    CLICK_ID.test(raw.ttclid)
  ) {
    body.ttclid = raw.ttclid;
  }

  return { body, ok: true };
}

let lastMissingTokenLog = 0;
const MISSING_TOKEN_LOG_INTERVAL_MS = 60_000;

/**
 * Handle one relayed event, end to end, with no framework in sight — the Next
 * route handlers in both apps are a dozen lines of header-reading around this.
 *
 * Returns a status rather than throwing, and never echoes anything from the
 * request body back to the caller: the reasons below describe our own
 * validation, so a prober learns nothing from them that reading this file
 * would not already tell them.
 */
export async function handleTikTokRelayRequest(
  request: TikTokRelayRequest,
  options: TikTokRelayOptions,
): Promise<TikTokRelayResponse> {
  const { allowedOrigins } = options;
  const log = options.onError ?? ((message: string) => console.error(message));

  if (!isAllowedOrigin(request, allowedOrigins)) {
    return { body: { reason: "origin not allowed", status: "rejected" }, status: 403 };
  }

  const parsed = parseBody(request.body);

  if (!parsed.ok) {
    return { body: { reason: parsed.reason, status: "rejected" }, status: 400 };
  }

  const config =
    options.config === undefined ? readTikTokServerConfig() : options.config;

  if (!config) {
    // Loudly, but not once per visitor: a missing token means every event is
    // failing, and a per-request log would bury the journal it is meant to
    // surface in.
    const now = (options.now ?? Date.now)();
    if (now - lastMissingTokenLog > MISSING_TOKEN_LOG_INTERVAL_MS) {
      lastMissingTokenLog = now;
      log(
        "tiktok-events: TIKTOK_EVENTS_API_ACCESS_TOKEN is not set — the server " +
          "channel is dropping every event. The browser pixel is unaffected.",
      );
    }

    return { body: { reason: "not configured", status: "unavailable" }, status: 503 };
  }

  const payload = buildTikTokEventPayload(
    {
      eventId: parsed.body.event_id,
      eventName: parsed.body.event,
      // From the server clock, never the request: the browser's clock is
      // both unreliable and attacker-controlled, and the relay is realtime.
      eventTime: Math.floor((options.now ?? Date.now)() / 1000),
      pageUrl: sanitizeUrl((request.body as Record<string, unknown>).page_url, allowedOrigins),
      properties: parsed.body.properties,
      referrer: sanitizeUrl((request.body as Record<string, unknown>).referrer),
      ttclid: parsed.body.ttclid,
      user: parsed.body.user,
    },
    {
      ip: request.ip ?? undefined,
      ttp: readCookie(request.cookieHeader, "_ttp"),
      userAgent: request.userAgent ?? undefined,
    },
    { testEventCode: config.testEventCode },
  );

  const result: TikTokDeliveryResult = await postTikTokEvent(
    payload,
    config.accessToken,
    options.fetchImpl,
  );

  if (!result.ok) {
    log(`tiktok-events: ${parsed.body.event} rejected — ${result.reason}`);

    return { body: { status: "failed" }, status: 502 };
  }

  return { body: { status: "accepted" }, status: 202 };
}

/** Test seam: the missing-token log throttle is module state. */
export function resetTikTokRelayLogThrottle(): void {
  lastMissingTokenLog = 0;
}
