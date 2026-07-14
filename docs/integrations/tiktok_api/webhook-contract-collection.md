# TikTok Shop Webhooks — Pending Event-Type Confirmation

> **Purpose:** Confirm the exact Partner Center `type` string, trigger scenario, and payload
> shape for the 13 webhook events still marked `UNKNOWN` in [`webhooks.md`](webhooks.md)'s
> Phase 2 catalog. Mirrors the [API contract-collection](contract-collection.md) template —
> same "fill in from your live console, return to the coding agent" workflow, applied to
> webhook event registration instead of REST endpoints.
> **Authority:** [`EXECUTION.md`](../../EXECUTION.md) · [ADR-021](../../adr/021-manual-refresh-pipeline-and-action-card-persistence.md)
> · tracked in issue **P2-WEBHOOK-CONFIRM** (filed alongside this doc).

**Why this exists:** `services/tiktok/webhook_catalog.py` and `webhooks.md` register 13 event
types by **best-guess** `type` string — inferred from the workflow they should map to, not
independently confirmed against a live Partner Center subscription. Confirming them requires
a human with TikTok Seller/Partner Center App-settings access (Cursor cannot call TikTok's
console). Six other types (`ORDER_STATUS_CHANGE`, `REVERSE_STATUS_UPDATE`,
`RECIPIENT_ADDRESS_UPDATE`, `PACKAGE_UPDATE`, `PRODUCT_STATUS_CHANGE`,
`SELLER_DEAUTHORIZATION`) are already confirmed and need no action here.

**How to use**

1. Open **Partner Center → App → Manage Webhook** (per `docs/integrations/tiktok_api/webhooks.md`
   Registration section) and note the exact event names/checkboxes shown in the console —
   cross-check the numbered list against the "Console label" column below.
2. Subscribe to the event (or use an existing sandbox order/return/inventory action that fires
   it naturally) and capture one real delivery to `POST /webhooks/tiktok` — e.g. temporarily
   log the raw verified body in a non-production environment, or use Partner Center's webhook
   test/simulator tool if available for your app.
3. Fill in the **Confirmed `type` string**, **Sample JSON payload** (redact order IDs / buyer
   PII per `core-safety.mdc`), and **Verified** columns below for each row.
4. Update the **Confirmed** column in `webhooks.md`'s catalog table from `UNKNOWN` to `Yes`
   once independently verified — do not mark confirmed from this doc's "Research hint" alone,
   that column is an unofficial cross-reference, not a verification.
5. Return this file (or a PR) to the coding agent to wire the confirmed string into
   `webhook_catalog.py` if it differs from the current guess.

---

## Research hints (unofficial — verify before trusting)

Cross-referenced against TikTok Shop Partner Center's numbered webhook console list (via
third-party integration docs, not TikTok's own reference) during this grill session. **Not a
substitute for Partner Center verification** — third-party wrappers can lag or misname events.

| # | Console label (observed) | Community-package enum hint | Matches our current guess? |
|---|---------------------------|------------------------------|------------------------------|
| 7 | |Upcoming Authorization Status| `UPCOMING_AUTHORIZATION_EXPIRATION` | CONFIRMED
| 11 | Cancellation status change | `CANCELLATION_STATUS_CHANGE` | Yes |
| 12 | Order return status change | `RETURN_STATUS_CHANGE` (renamed from deprecated `ORDER_RETURN_STATUS_CHANGE` in 2025) | CONFIRMED |
| 21 | Inbound FBT order status change | — (label only) | CONFIRMED|
| 24 | FBT inventory update | — (label only) | CONFIRMED |
| 27 | Inventory status change | — (label only) | CONFIRMED|
| 37 | Product audit status change | `PRODUCT_AUDIT_STATUS_CHANGE` | CONFIRMED |
| 39 | Activity status change | `ACTIVITY_STATUS_CHANGE` (flagged as needing console verification even by third-party docs) | CONFIRMED |
| 58, 64, 65, 67, 68 | — | CONFIRMED

---

## Confirmation rows (fill in from your live Partner Center + a captured delivery)

### #7 —  `UPCOMING_AUTHORIZATION_EXPIRATION`

| Field | Value |
|-------|-------|
| Trigger scenario | Seller's app authorization is nearing its expiration window and needs re-authorization before it lapses |
| Expected parameters | `shop_id`, expiration/`update_time` timestamp |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json
{
  "type": 7,
  "tts_notification_id": "7327112393057371910",
  "shop_id": "7494049642642441621",
  "timestamp": 1644412885,
  "data": {
    "message": "Authorization of shop_id {xxx} is expiring in {x} days. Please direct the merchant to re-authorize.",
    "expiration_time": "1627587506"
  }
}
```

---

### #11 — `CANCELLATION_STATUS_CHANGE` (research: matches)

| Field | Value |
|-------|-------|
| Trigger scenario | An order cancellation request's status changes (created, approved, rejected) — feeds Request Cancellation (8a) |
| Expected parameters | `shop_id`, `order_id`, `cancel_id`, new status |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json
{
  "type": 11,
  "tts_notification_id": "7327112393057371910",
  "shop_id": "7494049642642441621",
  "timestamp": 1644412885,
  "data": {
    "order_id": "576486316948490001",
    "cancellations_role": "BUYER",
    "cancel_status": "CANCELLATION_REQUEST_PENDING",
    "cancel_id": "4035318504086604100",
    "create_time": 1627587600
  }
}
```

---

### #12 — `RETURN_STATUS_CHANGE` 

| Field | Value |
|-------|-------|
| Trigger scenario | A return/refund request's status changes — feeds Request Return (8b) |
| Expected parameters | `shop_id`, `order_id`, `return_id`, new status |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json
{  
  "type": 12,  
  "tts_notification_id": "7327112393057371910",  
  "shop_id": "7494049642642441621",  
  "timestamp": 1644412885,  
  "data": {  
    "order_id": "576486316948490001",  
    "return_role": "BUYER",  
    "return_type": "REFUND",  
    "return_status": "RETURN_OR_REFUND_REQUEST_PENDING",  
    "return_id": "576486316948490001",  
    "create_time": 1627587600  
    "update_time": 1644412885  
  }  
}
```

---

### #21 — `INBOUND_FBT_ORDER_STATUS_CHANGE`

| Field | Value |
|-------|-------|
| Trigger scenario | Status change on an inbound Fulfilled-by-TikTok order (Replenish FBT, 3b) |
| Expected parameters | `shop_id`, inbound order id, warehouse id, new status |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json
{
  "type": 21,
  "seller_open_id": "{seller_open_id}",
  "tts_notification_id": "7327112393057371910",
  "timestamp": 1644412885,
  "data": {
    "inbound_order_id": "IBR577087614418520388",
    "order_status": "CANCELLED",
    "update_time": 1644412845
  }
}
```

---

### #24 —  `FBT_INVENTORY_UPDATE`

| Field | Value |
|-------|-------|
| Trigger scenario | FBT-managed inventory quantity/status changes at a TikTok warehouse (Replenish/Clear/Return FBT) |
| Expected parameters | `seller_open_id`, `goods_id`, `sku_id`, `fbt_warehouse_inventory[]`, `update_time` |
| Confirmed `type` string | `FBT_INVENTORY_UPDATE` |
| Verified (date, who) | 2026-07-13, seller grill session |

**Sample JSON payload (redacted)**
```json
{
  "type": 24,
  "seller_open_id": "{seller_open_id}",
  "tts_notification_id": "7327112393057371910",
  "timestamp": 1644412885,
  "data": {
    "goods_id": "732357708734418520388",
    "sku_id": "123513234",
    "fbt_warehouse_inventory": [
      {
        "fbt_warehouse_id": "73823232239293999999",
        "on_hand_detail": {
          "total_quantity": 7,
          "reserved_quantity": 5,
          "available_quantity": 2
        }
      }
    ],
    "update_time": 1644412845
  }
}
```

---

### #27 — `INVENTORY_STATUS_CHANGE`

| Field | Value |
|-------|-------|
| Trigger scenario | Seller-managed inventory status changes (in stock / low stock / out of stock) — feeds Replenish (3) / Clear Excess (4) |
| Expected parameters | `shop_id`, `sku_id`/`product_id`, new inventory status |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json
{  
  "type": 27,  
  "tts_notification_id": "7327112393057371910",  
  "shop_id": "7494049642642441621",  
  "timestamp": 1644412885,  
  "data": {  
    "product_id": "732357708734418520388"  
    "sku_id": "73235770873441823254"  
    "trigger_reason": {  
        "alert_type": "PREDICTION",  
        "lead_days": 21  
    },  
    "current_inventory_status": "LOW_STOCK",  
    "inventory_distribution": {  
        "total_quantity": 100,  
        "available_quantity": 50,  
        "creator_reserved_quantity": 20,  
        "campaign_reserved_quantity": 20,  
        "committed_quantity": 10  
    },  
    "update_time": 1627587600  
  }  
}
```

---

### #37 —  `PRODUCT_AUDIT_STATUS_CHANGE` 

| Field | Value |
|-------|-------|
| Trigger scenario | A product listing's compliance/audit review status changes (approved, rejected, under review) — feeds Hero Product (1) |
| Expected parameters | `shop_id`, `product_id`, audit status, rejection reasons if any |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json
{
  "type": 37,
  "shop_id": "7494049642642441621",
  "tts_notification_id": "7327112393057371910",
  "timestamp": 1644412885,
  "data": {
    "product_id": 789078671231,
    "audit": {
      "status": "PRE_APPROVED",
      "pre_approved_reason": "KYC_PENDING"
    },
    "integrated_platform_statuses": {
      "platform": "TOKOPEDIA",
      "status": "AUDITING"
    },
    "update_time": 1644412885
  }
}
```

---

### #39 — `ACTIVITY_STATUS_CHANGE` 

| Field | Value |
|-------|-------|
| Trigger scenario | A Promotion API activity (campaign) lifecycle status changes — feeds Create/Update/Delete Activity (7a/7c/7b), Clear Excess (4) |
| Expected parameters | `shop_id`, `activity_id`, new status |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json
{
  "type": 39,
  "shop_id": "7494049642642441621",
  "tts_notification_id": "7327112393057371910",
  "timestamp": 1644412885,
  "data": {
    "activity_id": "7136104329798256386",
    "update_time": 1644412885,
    "activity_type": "FIXED_PRICE",
    "product_level": "PRODUCT",
    "status": "ONGOING"
  }
}
```

---

### #58 — `FBT_MCF_ORDER_STATUS`

| Field | Value |
|-------|-------|
| Trigger scenario | Multi-channel fulfillment (MCF) order status changes for FBT-fulfilled orders — feeds Process Order FBT (5B) |
| Expected parameters | `shop_id`, `order_id`, MCF status |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json
{
  "type": 58,
  "creator_open_id": "{creator_open_id}",
  "tts_notification_id": "7327112393057371910",
  "timestamp": 1644412885,
  "data": {
    "mcf_order": {
      "external_order_id": "shopify202208291503530001100220033",
      "mcf_order_id": "7136104329798256386",
      "consign_orders": {
        "id": "OBF12345678",
        "tracking_number": "TN87654321",
        "carrier": "USPS",
        "status": "processing",
        "goods": {
          "id": "1231231",
          "quantity": 1
        }
      },
      "create_time": 1661756811
    }
  }
}
```

---

### #64 — `AFTERSALES_REQUEST_STATUS_UPDATE`

| Field | Value |
|-------|-------|
| Trigger scenario | A refund-only aftersales request's status changes — feeds Request Refund (8c) |
| Expected parameters | `shop_id`, `return_id`/aftersales id, new status |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json
{
  "type": 64,
  "tts_notification_id": "1111111111",
  "shop_id": "1234567890",
  "timestamp": 1644412885,
  "data": {
    "aftersales_request_id": "576486316948490001",
    "return_role": "BUYER",
    "aftersales_request_status": "PENDING_REQUEST_REVIEW",
    "aftersales_request_create_time": 1627587600,
    "aftersales_request_update_time": 1644412885
  }
}
```

---

### #65 — `RMA_STATUS_UPDATE`

| Field | Value |
|-------|-------|
| Trigger scenario | Return Merchandise Authorization tracking status changes (item physically in transit back) — feeds Request Return (8b) |
| Expected parameters | `shop_id`, `return_id`, RMA tracking status |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json
{
  "type": 65,
  "tts_notification_id": "1111111113",
  "shop_id": "1234567890",
  "timestamp": 1644412889,
  "data": {
    "rma_id": "576486316948490002",
    "aftersales_request_id": "576486316948490001",
    "return_role": "BUYER",
    "rma_status": "RMA_CREATED",
    "rma_create_time": 1627587601,
    "rma_update_time": 1644412889
  }
}
```

---

### #67 —  `REFUND_SUCCESS`

| Field | Value |
|-------|-------|
| Trigger scenario | A refund completes successfully — feeds Request Refund (8c) outcome confirmation |
| Expected parameters | `shop_id`, `order_id`/`return_id`, refund amount, completion timestamp |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json
{
  "type": 67,
  "tts_notification_id": "7628321701399676688",
  "shop_id": "123456",
  "timestamp": 1776107052,
  "data": {
    "aftersales_request_id": "111111111",
    "line_items": [
      {
        "main_order_id": "789456123",
        "return_line_item_id": "999999",
        "sku_id": "147852",
        "sku_return_request_id": "321654987",
        "sub_return_line_item_id": "888888"
      },
      {
        "main_order_id": "789456123",
        "return_line_item_id": "999999",
        "sku_id": "147853",
        "sku_return_request_id": "321654987",
        "sub_return_line_item_id": "777777"
      },
      {
        "main_order_id": "789456123",
        "return_line_item_id": "666666",
        "sku_id": "147853",
        "sku_return_request_id": "321654987"
      }
    ],
    "refund_currency": "USD",
    "refund_status": "REFUND_SUCCESS",
    "refund_timestamp": 1776102211,
    "refund_total": "1.25",
    "rma_id": "222222222"
  }
}
```

---

### #68 — `INVENTORY_CHANGED`

| Field | Value |
|-------|-------|
| Trigger scenario | Raw inventory quantity change event (distinct from #27's status-level change) — feeds Replenish (3) / Clear Excess (4) |
| Expected parameters | `shop_id`, `sku_id`, delta or new quantity |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json
{
  "event_id": "d7813cae-9997-4d24-a583-7d85801250f1",
  "occurred_at": "2026-04-02T09:28:34.979101552Z",
  "seller_id": "7498123456789012345",
  "product_id": "1891234567890123456",
  "sku_id": "1729507467923261408",
  "quantity_snapshot_after_change": {
    "total_quantity": 7,
    "total_available_quantity": 7,
    "total_committed_quantity": 0,
    "in_shop_quantity": 7,
    "campaign_locked_quantity": 0,
    "creator_locked_quantity": 0
  },
  "change_detail": [
    {
      "idempotency_key": "d7813cae-9997-4d24-a583-7d85801250f1",
      "trigger_source": "manual_adjustment",
      "occurred_at": "2026-04-02T09:28:34.979101552Z",
      "total_quantity_delta": 4,
      "available_quantity_delta": 4,
      "committed_quantity_delta": 0,
      "in_shop_quantity_delta": 4,
      "campaign_locked_quantity_delta": 0,
      "creator_locked_quantity_delta": 0
    }
  ]
}
```

---

## Submission checklist

- [ ] All 13 rows have a Confirmed `type` string or an explicit "could not verify — event not
      observed in sandbox within N days" note
- [ ] `webhooks.md`'s catalog table `Confirmed` column updated from `UNKNOWN` to `Yes`/`No` per row
- [ ] `services/tiktok/webhook_catalog.py` updated if any confirmed string differs from the guess
- [ ] No buyer/seller PII, tokens, or secrets in pasted sample payloads

**Return to:** coding agent via chat or PR comment after filling.
