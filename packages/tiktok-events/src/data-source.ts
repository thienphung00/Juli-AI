/**
 * The one TikTok data source both public Juli sites report into.
 *
 * TikTok Events Manager models Pixel (browser) and Events API (server) as two
 * CONNECTIONS on a single data source, not as two data sources. So this id is
 * both the `sdkid` the pixel loads with and the `event_source_id` the server
 * sends, and the two must never diverge: a second id would split one funnel
 * across two reports and silently disable deduplication, which TikTok keys on
 * (event name, event_id) *within* a data source.
 *
 * Not a secret — it ships in the page source of every visitor by construction.
 * It is a literal rather than a `NEXT_PUBLIC_*` variable on purpose: Next
 * inlines those at `next build` time only (#1905), which makes an env-sourced
 * pixel id *look* configurable while actually baking in whatever the build host
 * happened to have. A literal cannot be wrong in one environment and right in
 * another.
 */
export const TIKTOK_DATA_SOURCE_ID = "DAO9C6JC77U88MSNU74G";

/**
 * Every event name this codebase is allowed to emit.
 *
 * `Pageview` is fired by `ttq.page()` inside the base code and never goes
 * through `track()` — it is listed so the set of names reaching TikTok is
 * readable in one place, not because anything calls it.
 *
 * `ViewContent` and `CompleteRegistration` are TikTok *standard* events, so
 * they can be selected as campaign optimisation goals. `StartDemo` is a
 * *custom* event: TikTok's standard list has no name for "clicked through to a
 * product demo" (the closest, `SubmitForm` and `Contact`, describe something
 * else), and a wrong standard name is worse than an honest custom one because
 * it pollutes a goal the optimiser understands.
 */
export const TIKTOK_EVENTS = {
  pageView: "Pageview",
  viewContent: "ViewContent",
  startDemo: "StartDemo",
  completeRegistration: "CompleteRegistration",
} as const;

export type TikTokEventName = (typeof TIKTOK_EVENTS)[keyof typeof TIKTOK_EVENTS];

/**
 * The events sent through `track()` — i.e. everything except the automatic
 * pageview. This is the allowlist the server-side relay validates against, so
 * a public endpoint can never be used to inject an arbitrary event name into
 * the data source.
 */
export const TRACKED_EVENT_NAMES: readonly TikTokEventName[] = [
  TIKTOK_EVENTS.viewContent,
  TIKTOK_EVENTS.startDemo,
  TIKTOK_EVENTS.completeRegistration,
];

export function isTrackedEventName(value: unknown): value is TikTokEventName {
  return (
    typeof value === "string" &&
    TRACKED_EVENT_NAMES.includes(value as TikTokEventName)
  );
}

/**
 * The subset of TikTok event properties Juli sends. Deliberately closed rather
 * than an index signature: the same type validates the relay's request body,
 * and an open shape there would forward whatever a caller invented straight
 * into the data source.
 */
export interface TikTokEventProperties {
  content_id?: string;
  content_name?: string;
  content_type?: string;
  currency?: string;
  description?: string;
  value?: number;
}
