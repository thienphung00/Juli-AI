# Module: tiktok-events

## Responsibility

One TikTok data source (`DAO9C6JC77U88MSNU74G`), reported into by both public
sites. Owns the base pixel code, the event vocabulary, the deduplication id
both channels share, and the single normalise-then-SHA-256 path for user
identifiers.

## Public interface

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

## Dependencies

- `react` (peer) — for `TikTokPixel` only. No `next` dependency: both public
  apps consume the same component.

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
- This package never imports an app.

## Owners

- domain: web
- code: `packages/tiktok-events/`
