import type { TikTokEventName, TikTokEventProperties } from "./data-source";
import { newEventId } from "./event-id";
import { hashIdentity, type TikTokIdentity } from "./identity";

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
 * Record a conversion and return the `event_id` it was recorded under.
 *
 * The id is minted before the pixel is consulted and returned even when the
 * pixel never fired, because the server-side copy of this event needs the
 * *same* id to deduplicate against — and a blocked pixel is precisely the case
 * where the server copy is the only one that arrives.
 */
export function trackTikTokEvent(
  name: TikTokEventName,
  properties: TikTokEventProperties = {},
): string {
  const eventId = newEventId();

  callPixel((pixel) => pixel.track(name, properties, { event_id: eventId }));

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

  callPixel((pixel) => pixel.identify(hashed as Record<string, string>));
}
