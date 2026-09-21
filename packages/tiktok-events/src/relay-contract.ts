import type { TikTokEventName, TikTokEventProperties } from "./data-source";
import type { TikTokHashedIdentity } from "./identity";

/**
 * Where each app mounts its own relay route. Same path in both, because the
 * browser half of this contract lives in this package and has no way to ask
 * which app it is running in — and there is no reason for them to differ.
 */
export const TIKTOK_RELAY_PATH = "/api/tt/event";

/**
 * What the browser sends its own origin's relay route.
 *
 * Note what is NOT here: no event time, no IP, no user agent, no data source
 * id. Those are set server-side from the request itself. A client-supplied
 * value for any of them would be a value an attacker supplies, and none of
 * them is something the browser knows better than the server does.
 *
 * Identifiers arrive already hashed. The browser hashes them with the same
 * `hashIdentity` the server would have used, so the digest is identical either
 * way — and this way no raw email address is ever sent to a Juli server. On
 * the Demo, which signs in against Supabase directly from the browser, that
 * means Juli's own infrastructure still never sees one.
 */
export interface TikTokRelayEventBody {
  event: TikTokEventName;
  event_id: string;
  page_url?: string;
  properties?: TikTokEventProperties;
  referrer?: string;
  /** TikTok's click id, from the `ttclid` query parameter on the ad landing. */
  ttclid?: string;
  user?: TikTokHashedIdentity;
}
