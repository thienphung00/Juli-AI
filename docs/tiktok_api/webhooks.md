# Webhooks

TikTok Shop pushes event notifications to an ISV-registered HTTPS endpoint. Juli
receives, verifies HMAC, ACKs quickly, and hands off to ETL.

**Implementation:** `src/apps/api_gateway/services/webhook/`

> **UNKNOWN — not in extracted official pages:** Full event type catalog and retry
> policy. Register and verify events in Partner Center; update this file when
> event list is confirmed from official webhook documentation.

---

## Registration

Configure webhook URL in **TikTok Shop Partner Center** (App settings). Production
endpoint in Juli:

```
POST /webhooks/tiktok
```

Wired via `create_app(app_key=..., app_secret=..., handoff_fn=...)`.

---

## Delivery contract (implemented)

| Requirement | Juli behavior |
|-------------|---------------|
| ACK within 3s | Return `{"code": 0}` immediately; persistence async via ETL |
| Signature | `Authorization` header — HMAC-SHA256 |
| Required fields | `type` (event type), `shop_id` |
| Duplicates | Expected — dedup in `EtlConsumer` by `event_id` |

---

## Signature verification

Distinct from **API request signing** (query-param `sign`). Webhook verification:

```
sign_string = app_key + path + raw_body
expected    = HMAC-SHA256(app_secret, sign_string) → hex
```

| Field | Value |
|-------|-------|
| `path` | `/webhooks/tiktok` (literal, as registered) |
| Header | `Authorization: <signature>` |

Invalid or missing signature → HTTP 401, no handoff.

**Source:** `src/apps/api_gateway/services/webhook/app.py`

---

## Event routing

| Event prefix | ETL channel | Notes |
|--------------|-------------|-------|
| `LIVESTREAM*` | `livestream-events` | Post-stream signals |
| `CREATOR*` | `creator-events` | Affiliate creator changes |
| `AFFILIATE*` | `creator-events` | Affiliate program events |
| `SETTLEMENT*` | `settlement-events` | Finance signals |
| Other | `tiktok.{type_lower}` | Generic fallback |

**Source:** `EVENT_CATEGORY_ROUTES` in `app.py`

### Expected high-value events (operational — verify officially)

| Event type (illustrative) | Juli action |
|---------------------------|-------------|
| Order status change | Trigger incremental order sync / leakage scoring |
| Seller deauthorization | Stop polling, notify seller to re-auth |
| Authorization expiration warning | Proactive token refresh |
| Product update | Catalog sync |

Mark undocumented event names `UNKNOWN` until confirmed in Partner Center webhook docs.

---

## Handoff → ETL

```
Webhook POST → verify signature → parse JSON
            → handoff_fn(channel, shop_id, payload_bytes)
            → EtlConsumer.ingest (dedup, transform, persist)
```

`shop_id` is the TikTok shop identifier (matches `Shop.tiktok_shop_id`).

**Wiring:**

```python
from src.modules.ordering.use_cases.etl.consumer import EtlConsumer
from src.modules.ordering.api.ingestion.handoff import make_etl_handoff

handoff = make_etl_handoff(consumer)
app = create_app(app_key=..., app_secret=..., handoff_fn=handoff)
```

---

## Webhook vs polling (P2)

Per `data-sources.md` operational rules:

- **Webhooks** — low-latency signal for UX refresh (when registered).
- **Polling** — authoritative reconciliation; run at least every 15 minutes.
- Phase 2 primary ingestion path is **polling** (`EXECUTION.md` P2-1); webhooks
  are additive when Partner Center registration is complete.

---

## Failure modes

| Failure | HTTP | Handoff |
|---------|------|---------|
| Missing `Authorization` | 401 | No |
| Bad signature | 401 | No |
| Malformed JSON | 400 | No |
| Missing `type` or `shop_id` | 400 | No |
| Valid event | 200 `{"code":0}` | Yes |

Duplicate delivery is normal — idempotent upserts in ETL.
