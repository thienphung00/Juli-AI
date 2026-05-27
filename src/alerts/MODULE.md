# Module: alerts

## Responsibility
Configurable per-shop alert rules evaluated against incoming metric/anomaly
events, with cooldown deduplication and pluggable channel delivery (FCM in MVP).

## Public Interface

### Rule engine
- `configure_rules(session, shop_id, rules) -> list[AlertConfig]` — upsert thresholds per `alert_type`
- `evaluate_rules(session, shop_id, event, *, now=None) -> list[Alert]` — match rules, apply cooldown

### Delivery
- `deliver_alert(session, alert, adapter, *, device_token) -> DeliveryResult` — send + persist history
- `ChannelAdapter` — protocol for new channels (Zalo OA #40, etc.)
- `FcmAdapter` — FCM push with exponential backoff retries

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
