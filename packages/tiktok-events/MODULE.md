# Module: tiktok-events

## Responsibility

One TikTok data source (`DAO9C6JC77U88MSNU74G`), reported into by both public
sites. Owns the base pixel code, the event vocabulary, the deduplication id
both channels share, and the single normalise-then-SHA-256 path for user
identifiers.

## Public interface

### Browser (`@juli/tiktok-events`)

- `TikTokPixel` — server component rendering TikTok's base code; mount once per
  app, near the top of the root layout's `<body>`.
- `trackTikTokEvent(name, properties?)` — records a conversion, returns the
  `event_id` it was recorded under so a server copy can deduplicate against it.
- `trackTikTokPageView()` — a pageview for a client-side route change; the base
  code already fires the first one.
- `identifyTikTokUser(identity)` — hashed advanced matching; call before the
  event it should enrich.
- `TIKTOK_DATA_SOURCE_ID`, `TIKTOK_EVENTS`, `TRACKED_EVENT_NAMES`,
  `isTrackedEventName` — the vocabulary, and the allowlist a public relay
  validates against.
- `normalizeEmail`, `normalizeExternalId`, `sha256Hex`, `hashIdentity` —
  identifier normalisation, shared by browser and server so both derive the
  same digest.
- `captureTikTokClickId` / `readTikTokClickId` — keep the `ttclid` from the ad
  landing URL, which is handed over once and then gone.
- `relayTikTokEvent`, `TIKTOK_RELAY_PATH` — the server copy, beaconed to the
  app's own origin. `trackTikTokEvent` calls it; call it directly only in a
  test.

### Server (`@juli/tiktok-events/server`)

- `createTikTokRelayRoute({ allowedOrigins })` — the POST handler each app
  mounts at `TIKTOK_RELAY_PATH`. Validates, enriches, forwards.
- `handleTikTokRelayRequest` — the same thing with no framework, for tests.
- `buildTikTokEventPayload` — the Events API 2.0 body, pure.
- `postTikTokEvent` — the HTTP call to TikTok's consolidated endpoint.
- `readTikTokServerConfig` — reads `TIKTOK_EVENTS_API_ACCESS_TOKEN`; null,
  never a throw and never a default.

## Dependencies

- `react` (peer) — for `TikTokPixel` only. No `next` dependency: both public
  apps consume the same component, and the relay route is a plain
  `(Request) => Response`.

## Invariants

- One data source id for pixel and server alike. Two ids split one funnel into
  two reports and disable deduplication.
- Every tracked event carries an `event_id`. Deduplication is keyed on
  (event name, `event_id`) within 48 hours; without the id the two channels
  double-count.
- The vendor loader in `pixel-snippet.ts` is copied verbatim from Events
  Manager and is never reformatted.
- Identifiers are never sent unhashed, and never sent as empty strings — a
  field that cannot be normalised is omitted.
- No call into `window.ttq` may throw. A blocked pixel must not take the page
  down.
- The server entry point is a separate export path. Nothing under `./server`
  may be imported from a client component.
- The relay trusts nothing in the request body: event name against an
  allowlist, properties against a closed schema, identifiers only if they are
  SHA-256 digests, and the event time from the server clock.
- A missing access token is a logged 503, never a silent success.
- This package never imports an app.

## Operating it

[`docs/runbooks/tiktok-pixel-runbook.md`](../../docs/runbooks/tiktok-pixel-runbook.md)
— token setup, verification commands, and what bounds abuse of the relay.

## Owners

- domain: web
- code: `packages/tiktok-events/`
