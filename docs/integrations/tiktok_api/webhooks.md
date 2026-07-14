# Webhooks

TikTok Shop pushes event notifications to an ISV-registered HTTPS endpoint. Juli
receives, verifies HMAC, ACKs quickly, dispatches through the **Phase 2 catalog**
(#354), emits workflow-intent signals, and hands in-scope payloads to ETL.

**Implementation:** `backend/src/juli_backend/services/webhook/`

---

## Registration

Configure webhook URL in **TikTok Shop Partner Center** (App settings) as
`https://api.app-juli.com/webhooks/tiktok`. Production endpoint in Juli:

```
POST /webhooks/tiktok
```

**Deployed on the main API** (`juli_backend.api.app`, the `juli-api` systemd
service) — see `backend/src/juli_backend/api/routes/webhook_tiktok.py`. This is
the process Nginx and TikTok Partner Center actually reach; there is no separate
webhook service running. The route reuses `build_webhook_service(app_key=...,
app_secret=..., handoff_fn=...)` from `services/webhook/app.py`, the same
assembly used by the standalone `create_app(...)` kept for isolated testing.

Subscribe only to the **Phase 2 catalog** types below (~18 types). The remaining
~50 catalog slots (Affiliate, Customer Service, Finance beyond invoicing, etc.) are
**not subscribed** in Phase 2.

---

## Delivery contract (implemented)

| Requirement | Juli behavior |
|-------------|---------------|
| ACK within 3s | Return `{"code": 0}` immediately; persistence async via ETL |
| Signature | `Authorization` header — HMAC-SHA256 |
| Required fields | `type` (numeric catalog id or event-name string). Shop key: top-level `shop_id`, or for **#68 `INVENTORY_CHANGED`** `data.seller_id` when `shop_id` is absent (live deliveries use `seller_open_id` + `seller_id`) |
| Duplicates | Expected — dedup in `EtlConsumer` by `event_id` (including `data.event_id` on #68) |

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

**Source:** `backend/src/juli_backend/services/webhook/app.py`

---

## Phase 2 catalog (authoritative)

Registry: `backend/src/juli_backend/services/tiktok/webhook_catalog.py`  
Workflow mapping: `docs/product/execution_layer.md` — Webhook catalog in use

| # | Event type (Partner Center) | ETL channel | Workflow(s) | Confirmed |
|---|----------------------------|-------------|-------------|-----------|
| 1 | `ORDER_STATUS_CHANGE` | `tiktok.order_status_change` | Process Order (5) | Yes |


| 2 | `REVERSE_STATUS_UPDATE` | `tiktok.reverse_status_update` | Request 8a/8b/8c intake | **CONFIRMED** |
| 3 | `RECIPIENT_ADDRESS_UPDATE` | `tiktok.recipient_address_update` | Process Order (5) | Yes |
| 4 | `PACKAGE_UPDATE` | `tiktok.package_update` | Split Package (6) | Yes |
| 5 | `PRODUCT_STATUS_CHANGE` | `tiktok.product_status_change` | Hero Product (1), Optimize (2) | Yes |
| 6 | `SELLER_DEAUTHORIZATION` | `tiktok.account.lifecycle` | Account — pause automations | Yes |
| 7 | `UPCOMING_AUTHORIZATION_EXPIRATION` | `tiktok.account.lifecycle` | Account — re-auth prompt | **CONFIRMED** |
| 11 | `CANCELLATION_STATUS_CHANGE` | `tiktok.cancellation_status_change` | Request Cancellation (8a) | **CONFIRMED** |
| 12 | `RETURN_STATUS_CHANGE` | `tiktok.returns.raw` | Request Return (8b) | **CONFIRMED** |
| 21 | `INBOUND_FBT_ORDER_STATUS_CHANGE` | `tiktok.inbound_fbt_order_status` | Replenish FBT (3b) | **UNKNOWN** |
| 24 | `FBT_INVENTORY_UPDATE` | `tiktok.fbt_inventory_update` | Replenish/Clear/Return FBT | **CONFIRMED** |
| 27 | `INVENTORY_STATUS_CHANGE` | `tiktok.inventory_status_change` | Replenish (3), Clear (4) | **CONFIRMED** |
| 37 | `PRODUCT_AUDIT_STATUS_CHANGE` | `tiktok.product_audit_status_change` | Hero Product (1) | **CONFIRMED** |
| 39 | `ACTIVITY_STATUS_CHANGE` | `tiktok.activity_status_change` | Activity 7a/7b/7c, Clear (4) | **CONFIRMED** |
| 58 | `FBT_MCF_ORDER_STATUS` | `tiktok.fbt_mcf_order_status` | Process Order FBT (5B) | **CONFIRMED** |
| 64 | `AFTERSALES_REQUEST_STATUS_UPDATE` | `tiktok.aftersales_request_status` | Request Refund (8c) | **CONFIRMED** |
| 65 | `RMA_STATUS_UPDATE` | `tiktok.rma_status_update` | Request Return (8b) | **CONFIRMED** |
| 67 | `REFUND_SUCCESS` | `tiktok.refund_success` | Request Refund (8c) | **CONFIRMED** |
| 68 | `INVENTORY_CHANGED` | `tiktok.inventory.raw` | Replenish (3), Clear (4) | **CONFIRMED** |

**ALL ARE CONFIRMED**

### Deferred (Phase 3+) — not subscribed, not routed

Prefixes: `AFFILIATE`, `CREATOR`, `LIVESTREAM`, `SETTLEMENT`, `NEW_CONVERSATION`,
`NEW_MESSAGE`, `CUSTOMER_SERVICE`, `FINANCE_`.

These receive HTTP 200 ACK but **no** Phase 2 ETL handoff or workflow signal.

---

## Dispatch pipeline

```
Webhook POST → verify signature → parse JSON
            → catalog dispatch (handler + workflow_webhook_signals)
            → handoff_fn(channel, shop_id, payload_bytes)  [in-scope only]
            → EtlConsumer.ingest (dedup, transform, persist)
```

Account/platform events (#6, #7) write side effects only — no ETL handoff.

`shop_id` is the TikTok shop identifier (matches `Shop.tiktok_shop_id`).
For `#68 INVENTORY_CHANGED`, live Partner Center deliveries omit top-level
`shop_id` and send `data.seller_id` instead — the receiver maps that to the
handoff shop key (see `TikTokWebhookPayload.from_dict`).

---

## Webhook vs polling (P2)

Per `data-sources.md` operational rules:

- **Webhooks** — low-latency workflow gates and incremental sync triggers.
- **Polling (Fujiwa)** — authoritative reconciliation; run at least every 15 minutes.
- Phase 2 ingestion is **polling + catalog webhooks**; polling remains the backstop.

```
Webhook POST → verify HMAC → parse → catalog dispatch → ETL upsert
Polling (Fujiwa) → authoritative reconciliation every ≤15 min
```

---

## Failure modes

| Failure | HTTP | Handoff |
|---------|------|---------|
| Missing `Authorization` | 401 | No |
| Bad signature | 401 | No |
| Malformed JSON | 400 | No |
| Missing `type` or `shop_id` | 400 | No |
| Phase 2 catalog event | 200 `{"code":0}` | Yes (except #6/#7) |
| Deferred out-of-scope event | 200 `{"code":0}` | No |

Duplicate delivery is normal — idempotent upserts in ETL and workflow signals.
