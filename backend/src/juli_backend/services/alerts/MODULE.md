# Module: alerts

## Responsibility
Configurable per-shop alert rules evaluated against incoming metric/anomaly
events, with cooldown deduplication and pluggable channel delivery (FCM + Zalo OA).

## Public Interface

### Rule engine
- `configure_rules(session, shop_id, rules) -> list[AlertConfig]` — upsert thresholds per `alert_type`
- `evaluate_rules(session, shop_id, event, *, now=None) -> list[Alert]` — match rules, apply cooldown

### Delivery
- `deliver_alert(session, alert, adapter, *, device_token) -> DeliveryResult` — send + persist history
- `ChannelAdapter` — protocol for pluggable channels (FCM, Zalo OA, …)
- `FcmAdapter` — FCM push with exponential backoff retries
- `ZaloOaAdapter` — Zalo OA text messages (`device_token` = Zalo user id); retries + backoff

### Types
- `AlertEvent`, `Alert`, `RuleConfigInput`, `DeliveryResult`

## Dependencies
- `src.data` — `AlertConfig`, `AlertHistory`, `AlertConfigsRepo`, `AlertHistoryRepo` (read/write)

## Invariants
- Default cooldown: 3600 seconds per `alert_type` (overridable in threshold JSON)
- No duplicate alerts for the same `alert_type` inside the cooldown window
- Core engine does not import channel implementations; callers inject `ChannelAdapter`
- User-facing copy in plain Vietnamese

## Owners
- domain: alerts
- code: src/alerts/

## Status: LEGACY (fast track P53, D62, 2026-10-18)

Marker only — no behaviour changed, nothing moved or deleted (owner-approved audit cleanup,
`juli-audit/backend.md`). No production importer, no test, no route, task or flag: the Zalo/FCM alert engine (ADR-005) was never wired. The `alert_config` / `alert_history` tables, models and repositories in `database` stay. Deleting the package is audit item C3 and needs the owner to confirm alerts are off the roadmap.
