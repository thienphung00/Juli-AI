import type { TikTokEventName, TikTokEventProperties } from "./data-source";
import { newEventId } from "./event-id";
import {
  hashIdentity,
  type TikTokHashedIdentity,
  type TikTokIdentity,
} from "./identity";
import { relayTikTokEvent } from "./relay";

/**
 * The slice of `window.ttq` this codebase calls. The base code installs every
 * one of these synchronously as a queueing stub, so they are safe to call
 * before `events.js` has loaded.
 */
interface TikTokPixelApi {
  identify: (identity: Record<string, string>) => void;
  page: () => void;
  track: (
    event: string,
    properties?: TikTokEventProperties,
    options?: { event_id: string },
  ) => void;
}

function getPixel(): TikTokPixelApi | null {
  if (typeof window === "undefined") {
    return null;
  }

  const ttq = (window as unknown as { ttq?: TikTokPixelApi }).ttq;

  return typeof ttq?.track === "function" ? ttq : null;
}

/**
 * Every call into `ttq` goes through here. A pixel blocked by an extension
 * leaves behind a partially-initialised global often enough that calling it
 * throws, and an exception raised inside a React effect would take the page
 * down with it. Analytics failing is not a reason for the site to fail.
 */
function callPixel(invoke: (pixel: TikTokPixelApi) => void): void {
  const pixel = getPixel();

  if (!pixel) {
    return;
  }

  try {
    invoke(pixel);
  } catch {
    // Intentionally swallowed — see above.
  }
}

/**
 * A pageview for a client-side route change. The base code already fires the
 * first one; single-page navigations produce no document load, so nothing else
 * would.
 */
export function trackTikTokPageView(): void {
  callPixel((pixel) => pixel.page());
}

/**
 * Identifiers established by the most recent `identifyTikTokUser` call, so the
 * server copy of an event can carry what the pixel copy carries.
 *
 * Module state mirrors how the pixel itself works: `identify` seeds matching
 * state that subsequent events read. It lives for one document, which is the
 * same lifetime `ttq`'s own copy has.
 */
let currentIdentity: TikTokHashedIdentity = {};

/**
 * Record a conversion on both channels and return the `event_id` they share.
 *
 * Both, always, with one id — that is what makes the two channels additive
 * instead of double-counting. TikTok collapses a pixel event and an Events API
 * event with the same name and the same `event_id` within 48 hours into one
 * conversion, keeping the first and enriching it with the second. So the
 * browser copy wins when it arrives, the server copy covers the visitor whose
 * blocker ate it, and neither case inflates the number.
 *
 * The id is minted before the pixel is consulted and returned even when the
 * pixel never fired, because a blocked pixel is precisely the case where the
 * server copy is the only one that arrives.
 */
export function trackTikTokEvent(
  name: TikTokEventName,
  properties: TikTokEventProperties = {},
): string {
  const eventId = newEventId();

  callPixel((pixel) => pixel.track(name, properties, { event_id: eventId }));
  relayTikTokEvent(name, eventId, properties, currentIdentity);

  return eventId;
}

/**
 * Attach hashed identifiers to this visitor's subsequent events.
 *
 * Call it *before* the event it should enrich: `identify` seeds state the next
 * `track` reads, it does not retroactively decorate events already sent.
 * Values are hashed here rather than handed to TikTok raw — TikTok accepts
 * both, but pre-hashing means no unhashed address is ever written into a
 * global, and it guarantees the browser and the server derive the identical
 * digest from the identical input.
 */
export async function identifyTikTokUser(
  identity: TikTokIdentity,
): Promise<void> {
  const hashed = await hashIdentity(identity);

  if (Object.keys(hashed).length === 0) {
    return;
  }

  currentIdentity = { ...currentIdentity, ...hashed };
  callPixel((pixel) => pixel.identify(hashed as Record<string, string>));
}

/** Test seam: drop identifiers established in this document. */
export function resetTikTokIdentity(): void {
  currentIdentity = {};
}
