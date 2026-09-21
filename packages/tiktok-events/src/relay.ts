import type { TikTokEventName, TikTokEventProperties } from "./data-source";
import type { TikTokHashedIdentity } from "./identity";
import { readTikTokClickId } from "./click-id";
import { TIKTOK_RELAY_PATH, type TikTokRelayEventBody } from "./relay-contract";

/**
 * Send this app's own origin a copy of an event, for the server to forward to
 * TikTok's Events API under the same `event_id` the pixel used.
 *
 * `sendBeacon` rather than `fetch`, because the event this matters most for is
 * a click on a link that navigates away: a normal fetch is cancelled when the
 * document unloads, and `StartDemo` would be lost exactly when it fires.
 * `keepalive` is the fallback for the same reason.
 *
 * Failure here is silent on purpose. The pixel has already recorded the event;
 * the relay exists to cover the case where it did not, and a visitor must
 * never see an analytics error.
 */
export function relayTikTokEvent(
  eventName: TikTokEventName,
  eventId: string,
  properties: TikTokEventProperties,
  user: TikTokHashedIdentity,
): void {
  if (typeof window === "undefined") {
    return;
  }

  const body: TikTokRelayEventBody = {
    event: eventName,
    event_id: eventId,
    page_url: window.location.href,
    properties,
  };

  if (document.referrer) {
    body.referrer = document.referrer;
  }

  const clickId = readTikTokClickId();
  if (clickId) {
    body.ttclid = clickId;
  }

  if (Object.keys(user).length > 0) {
    body.user = user;
  }

  const serialized = JSON.stringify(body);

  try {
    if (typeof navigator.sendBeacon === "function") {
      const blob = new Blob([serialized], { type: "application/json" });

      if (navigator.sendBeacon(TIKTOK_RELAY_PATH, blob)) {
        return;
      }
    }

    void fetch(TIKTOK_RELAY_PATH, {
      body: serialized,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      keepalive: true,
      method: "POST",
    }).catch(() => undefined);
  } catch {
    // See above.
  }
}
