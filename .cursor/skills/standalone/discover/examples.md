# Blueprint Examples

## Example 1: TikTok Order Webhook Sync

### User Request

> "Process TikTok order webhooks and keep the dashboard in sync."

### Clarifying Questions Asked

1. Webhook or polling only? → Webhook primary; 15-minute reconciliation poll as backup
2. Idempotency key? → `(event_type, shop_id, entity_id, update_time)`
3. Failure handling? → ETL DLQ handoff + structured logs; no silent drops
4. Multi-tenant isolation? → All writes scoped by `shop_id` via repos
5. Data source allowed? → TikTok Shop Official API + webhooks only (see `data-sources.md` #1, #4)

### Generated Docs

```
docs/features/tiktok-order-webhook-sync/
  PRD.md
  architecture.md
  api-contracts.md
  db-changes.md
  edge-cases.md
```

### Key Architecture Decision

- `src/services/webhook` verifies HMAC and hands off to ETL
- Consumers upsert via `src/data` repos
- `src/api` exposes read models to `web/` and `ios/`

---

## Example 2: Post-Stream Livestream Scoring

### User Request

> "Score livestreams after they end and flag revenue anomalies."

### Clarifying Questions Asked

1. Realtime stream telemetry? → **No** — post-stream API summaries only (`data-sources.md` #7, #8)
2. Minimum history for anomalies? → 30 sessions; moving-average fallback below
3. Writes to DB? → Scoring module is read-only; persistence stays in `src/data` callers
4. Sentiment? → Lexicon-based Vietnamese comments; no external NLP in MVP

### Generated Docs

```
docs/features/livestream-post-stream-scoring/
  PRD.md
  architecture.md
  edge-cases.md
```

### Key Architecture Decision

- Implement in `src/intelligence/scoring/`
- Document retention curves as **estimates**, not measured minute-by-minute viewers

---

## Example 3: Seller Alert on Low Inventory

### User Request

> "Notify the seller when SKU stock drops below threshold."

### Clarifying Questions Asked

1. Channels? → FCM always-on; Zalo OA when template approved
2. Trigger source? → Inventory sync from TikTok API (#1) + webhook updates (#4)
3. Rate limits? → Debounce per SKU per shop; no alert storms
4. PII in alert body? → Product name + SKU only; no buyer data

### Generated Docs

```
docs/features/low-inventory-alerts/
  PRD.md
  architecture.md
  api-contracts.md
  edge-cases.md
```

### Key Architecture Decision

- Alert dispatcher as channel-pluggable service (planned layer in `map.md`)
- Threshold config stored in `src/data` (`AlertConfig`)
