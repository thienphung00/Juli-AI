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
| 7 | Auth Expire | `AUTH_EXPIRE` | **No** — we guessed `UPCOMING_AUTHORIZATION_EXPIRATION`; likely wrong, verify first |
| 11 | Cancellation status change | `CANCELLATION_STATUS_CHANGE` | Yes |
| 12 | Order return status change | `RETURN_STATUS_CHANGE` (renamed from deprecated `ORDER_RETURN_STATUS_CHANGE` in 2025) | Yes |
| 21 | Inbound FBT order status change | — (label only) | Plausible, unverified |
| 24 | FBT inventory update | — (label only) | Plausible, unverified |
| 27 | Inventory status change | — (label only) | Plausible, unverified |
| 37 | Product audit status change | `PRODUCT_AUDIT_STATUS_CHANGE` | Yes |
| 39 | Activity status change | `ACTIVITY_STATUS_CHANGE` (flagged as needing console verification even by third-party docs) | Plausible, unverified |
| 58, 64, 65, 67, 68 | — | No hint found this pass | Unverified — no signal either way |

---

## Confirmation rows (fill in from your live Partner Center + a captured delivery)

### #7 — Best guess `UPCOMING_AUTHORIZATION_EXPIRATION` (research suggests `AUTH_EXPIRE` — verify first)

| Field | Value |
|-------|-------|
| Trigger scenario | Seller's app authorization is nearing its expiration window and needs re-authorization before it lapses |
| Expected parameters | `shop_id`, expiration/`update_time` timestamp |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json

```

---

### #11 — Best guess `CANCELLATION_STATUS_CHANGE` (research: matches)

| Field | Value |
|-------|-------|
| Trigger scenario | An order cancellation request's status changes (created, approved, rejected) — feeds Prevent Cancellation (8a) |
| Expected parameters | `shop_id`, `order_id`, `cancel_id`, new status |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json

```

---

### #12 — Best guess `RETURN_STATUS_CHANGE` (research: matches; was `ORDER_RETURN_STATUS_CHANGE` pre-2025)

| Field | Value |
|-------|-------|
| Trigger scenario | A return/refund request's status changes — feeds Prevent Return (8b) |
| Expected parameters | `shop_id`, `order_id`, `return_id`, new status |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json

```

---

### #21 — Best guess `INBOUND_FBT_ORDER_STATUS_CHANGE`

| Field | Value |
|-------|-------|
| Trigger scenario | Status change on an inbound Fulfilled-by-TikTok order (Replenish FBT, 3b) |
| Expected parameters | `shop_id`, inbound order id, warehouse id, new status |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json

```

---

### #24 — Best guess `FBT_INVENTORY_UPDATE`

| Field | Value |
|-------|-------|
| Trigger scenario | FBT-managed inventory quantity/status changes at a TikTok warehouse (Replenish/Clear/Return FBT) |
| Expected parameters | `shop_id`, `sku_id`/`product_id`, warehouse id, quantity |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json

```

---

### #27 — Best guess `INVENTORY_STATUS_CHANGE`

| Field | Value |
|-------|-------|
| Trigger scenario | Seller-managed inventory status changes (in stock / low stock / out of stock) — feeds Replenish (3) / Clear Excess (4) |
| Expected parameters | `shop_id`, `sku_id`/`product_id`, new inventory status |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json

```

---

### #37 — Best guess `PRODUCT_AUDIT_STATUS_CHANGE` (research: matches, confirmed constant name in third-party reference)

| Field | Value |
|-------|-------|
| Trigger scenario | A product listing's compliance/audit review status changes (approved, rejected, under review) — feeds Hero Product (1) |
| Expected parameters | `shop_id`, `product_id`, audit status, rejection reasons if any |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json

```

---

### #39 — Best guess `ACTIVITY_STATUS_CHANGE` (research: plausible but flagged as needing console verification)

| Field | Value |
|-------|-------|
| Trigger scenario | A Promotion API activity (campaign) lifecycle status changes — feeds Create/Update/Delete Activity (7a/7c/7b), Clear Excess (4) |
| Expected parameters | `shop_id`, `activity_id`, new status |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json

```

---

### #58 — Best guess `FBT_MCF_ORDER_STATUS`

| Field | Value |
|-------|-------|
| Trigger scenario | Multi-channel fulfillment (MCF) order status changes for FBT-fulfilled orders — feeds Process Order FBT (5B) |
| Expected parameters | `shop_id`, `order_id`, MCF status |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json

```

---

### #64 — Best guess `AFTERSALES_REQUEST_STATUS_UPDATE`

| Field | Value |
|-------|-------|
| Trigger scenario | A refund-only aftersales request's status changes — feeds Prevent Refund (8c) |
| Expected parameters | `shop_id`, `return_id`/aftersales id, new status |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json

```

---

### #65 — Best guess `RMA_STATUS_UPDATE`

| Field | Value |
|-------|-------|
| Trigger scenario | Return Merchandise Authorization tracking status changes (item physically in transit back) — feeds Prevent Return (8b) |
| Expected parameters | `shop_id`, `return_id`, RMA tracking status |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json

```

---

### #67 — Best guess `REFUND_SUCCESS`

| Field | Value |
|-------|-------|
| Trigger scenario | A refund completes successfully — feeds Prevent Refund (8c) outcome confirmation |
| Expected parameters | `shop_id`, `order_id`/`return_id`, refund amount, completion timestamp |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json

```

---

### #68 — Best guess `INVENTORY_CHANGED`

| Field | Value |
|-------|-------|
| Trigger scenario | Raw inventory quantity change event (distinct from #27's status-level change) — feeds Replenish (3) / Clear Excess (4) |
| Expected parameters | `shop_id`, `sku_id`, delta or new quantity |
| Confirmed `type` string | |
| Verified (date, who) | |

**Sample JSON payload (redacted)**
```json

```

---

## Submission checklist

- [ ] All 13 rows have a Confirmed `type` string or an explicit "could not verify — event not
      observed in sandbox within N days" note
- [ ] `webhooks.md`'s catalog table `Confirmed` column updated from `UNKNOWN` to `Yes`/`No` per row
- [ ] `services/tiktok/webhook_catalog.py` updated if any confirmed string differs from the guess
- [ ] No buyer/seller PII, tokens, or secrets in pasted sample payloads

**Return to:** coding agent via chat or PR comment after filling.
