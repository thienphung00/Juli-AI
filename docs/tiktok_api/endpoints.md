# Endpoints

Categorized inventory of TikTok Shop Open API endpoints relevant to Juli-AI.
Versioned paths are from official Partner Center docs; **Implemented path** reflects
the current Python client — reconcile during P2-1 if paths diverge.

**Source:** [Developer Guide](https://partner.tiktokshop.com/docv2/page/tts-developer-guide),
[Java SDK example](https://partner.tiktokshop.com/docv2/page/integrate-java-sdk),
`src/modules/catalog/domain/integrations/tiktok/resources/`.

---

## Vendor → Juli entity mapping

| TikTok entity | Juli model / edge | Notes |
|---------------|-------------------|-------|
| Shop (`id`, `cipher`) | `Shop` | Shop-scoped access everywhere |
| Product / SKU | `Product` | Catalog + Growth Copilot inputs |
| Order / line items | `Order` | Revenue Leakage Detection |
| Return / refund | `Order` status edges | Anomaly detector features |
| Affiliate Creator | `Creator` | Scope-gated; P2 affiliate polling |
| Livestream session | Post-stream summary | **Not** realtime telemetry (forbidden #8) |
| Settlement | Finance signal | `pending` 7–14d; out of P2 core UI |
| Ad performance | Ads signal | P2 Growth Copilot — client **not yet implemented** |
| Buyer | Masked `buyer_id` only | No PII (#17) |

---

## Authorization

### GET `/authorization/202309/shops`

| | |
|---|---|
| **Permissions** | Valid shop access token |
| **Pagination** | N/A — returns all authorized shops |
| **Juli use** | OAuth callback provisioning, multi-shop picker |

**Response:** `shops[]` with `id`, `cipher`, `name`, `region`, `seller_type`.

**Source:** [call-get-authorized-shops](https://partner.tiktokshop.com/docv2/page/call-get-authorized-shops)

---

## Account Health / Performance (Seller)

**Status:** **UNKNOWN** — not confirmed in extracted Partner Center docs.  
**P2-1 gate:** Verify via Partner Center **API Reference** + **API Testing Tool** (login required).  
**Forbidden:** No Seller Center scraping ([Forbidden #9](../architecture/data-sources.md#forbidden--always-non-negotiable)).

### What we want (platform signals)

| Platform signal | Used for | Known to exist in policy docs | Partner API exposure (current) |
|----------------|----------|-------------------------------|--------------------------------|
| Seller VP score | Affiliate enrollment suppression; risk banding | Yes | **UNKNOWN** |
| Seller AHR score | Post-July 2026 health gating | Yes | **UNKNOWN** |
| Seller SFCR / LDR | Proxy operational health | Yes | **UNKNOWN** |
| Balance withholding status | Treat balance as `frozen` | Yes | **UNKNOWN** |
| Violation record events | Alerting + appeal-window tracking | Yes | **UNKNOWN** (webhook catalog not extracted) |

### Degraded-mode contract (until verified)

Juli must **not** assume numeric VP/AHR/CHR scores are exposed. Phase 2 should follow a
three-tier read strategy:

| Tier | `health_data_source` | Inputs | Behavior |
|------|-----------------------|--------|----------|
| 1 (preferred) | `api` | Official account-health fields (VP/AHR/withholding/violations) | Use exact platform thresholds. |
| 2 (degraded) | `proxy` | Computed proxies from Orders / Products / Affiliate polling | Approximate risk bands; never fabricate VP/AHR numbers. |
| 3 (explicit gap) | `unavailable` | No trustworthy fields available | UI shows “health score unavailable”; alerts limited to what can be proven (e.g. product audit status). |

### Proxy signals we can compute if raw fields exist (UNVERIFIED schemas)

| Proxy | Candidate source endpoint | Notes |
|-------|---------------------------|-------|
| Seller-fault cancellation rate (SFCR proxy) | Orders search/detail | Requires cancel reason / seller-fault markers (schema not extracted). |
| Late dispatch rate (LDR proxy) | Orders search/detail | Requires dispatch timestamps + SLA (schema not extracted). |
| Return/refund rate | Orders + return/refund edges | Partial mapping exists; confirm fields in API Reference. |
| Listing suspension / audit status | Products search/details | `products[].audit.status` already mapped. |
| Affiliate enrollment blocked | Affiliate endpoints errors | Behavioral signal: `PermissionDeniedError (100003)`; not a VP/AHR numeric measure. |

> **Action (P2-1):** Add account-health endpoints + schemas here once verified; update
> `docs/architecture/data-sources.md` + `docs/system-design.md` to reflect confirmed fields.

---

## Token (no request signing)

### POST `/api/v2/token/get`

Exchange OAuth `auth_code` for tokens. See [authentication.md](authentication.md).

### POST `/api/v2/token/refresh`

Rotate refresh token. See [authentication.md](authentication.md).

---

## Products

### Official (versioned)

| | |
|---|---|
| **Method** | `POST` |
| **Official path** | `/product/202502/products/search` (SDK: `ProductV202502Api`) |
| **Permissions** | Shop token + `shop_cipher` |
| **Pagination** | `page_token` / `next_page_token` cursor |

**Request body (documented):**

| Field | Type | Required |
|-------|------|----------|
| `status` | string | Optional — `ALL`, `ON_SALE`, `OFF_SALE`, `UNDER_AUDIT` |

**Response `data`:**

| Field | Type |
|-------|------|
| `products[]` | array |
| `products[].id` | string → `Product.external_id` |
| `products[].create_time` | integer |
| `products[].audit.status` | string |
| `next_page_token` | string |

**Source:** [integrate-java-sdk](https://partner.tiktokshop.com/docv2/page/integrate-java-sdk)

### Implemented (`ProductsResource`)

| Method | Path | Methods |
|--------|------|---------|
| POST | `/api/products/search` | `search`, `search_all` |
| GET | `/api/products/details` | `get_details(product_id)` |

**Body filters:** `status`, `update_time_from`, `update_time_to`, `page_size`.

> **DISCREPANCY:** Client uses unversioned `/api/products/*` paths. Verify against
> Partner Center API Reference during P2-1; upgrade to `202502` paths if required.

**Phase:** P2 (`data-sources.md` — TikTok Products row).

---

## Orders

### Implemented (`OrdersResource`)

| Method | Path | Client method |
|--------|------|---------------|
| POST | `/api/orders/search` | `search`, `search_all` |
| POST | `/api/orders/detail/query` | `get_details(order_ids)` |

**Search body:**

| Field | Type | Notes |
|-------|------|-------|
| `status` | string | Filter by order status |
| `update_time_from` | integer | Unix — incremental sync key |
| `update_time_to` | integer | Window end |
| `page_size` | integer | Default 50 in `search_all` |

**Pagination:** `page_token` cursor via `TikTokClient.get_all_pages`, items key `orders`.

**Juli use:** Revenue Leakage Detection — returns, refunds, cancellation patterns.

**Constraints:** Bounded history ~90d (operational assumption per `data-sources.md`).

**Phase:** P2.

> **UNKNOWN — not in extracted official pages:** Full request/response schema for
> `/api/orders/search`. Confirm in Partner Center API Reference before P2-1.

---

## Affiliate — Creators

### Implemented (`CreatorsResource`)

| Method | Path | Client method |
|--------|------|---------------|
| POST | `/api/affiliate/creators/search` | `list`, `list_all` |
| GET | `/api/affiliate/creators/details` | `get(creator_id)` |

**Permissions:** Affiliate scope — `PermissionDeniedError` if seller has not approved.

**Juli mapping:** `Creator` — affiliate cancellation rates for fraud detection.

**Phase:** P2.

---

## Affiliate — Livestreams (post-stream only)

### Implemented (`LivestreamsResource`)

| Method | Path | Client method |
|--------|------|---------------|
| POST | `/api/affiliate/livestreams/search` | `list`, `list_all` |
| GET | `/api/affiliate/livestreams/details` | `get(livestream_id)` |

**Search body:** `creator_id`, `start_time`, `end_time`, `page_size`, `page_token`.

**Constraint:** Post-stream summaries only. Realtime in-stream data is **Forbidden** (#8).

**Phase:** Later / out of P2 core per `map.md` pending cleanup (polling worker removal).

---

## Inventory

### Implemented (`InventoryResource`)

| Method | Path | Client method |
|--------|------|---------------|
| POST | `/api/inventory/search` | `search` |
| POST | `/api/inventory/update` | `update` |

**Phase:** Out of P2 scope — `sync_inventory` slated for removal per `map.md`.

---

## Finance — Settlements

### Implemented (`SettlementsResource`)

| Method | Path | Client method |
|--------|------|---------------|
| POST | `/api/finance/settlements/search` | `list`, `list_all` |

**Search body:** `settle_time_from`, `settle_time_to`, `page_size`, `page_token`.

**Operational rule:** Treat amounts as `pending` for 7–14 days.

**Phase:** Out of P2 core — `sync_settlements` slated for removal per `map.md`.

---

## Ads

**P2 requirement** per [`EXECUTION.md`](../../EXECUTION.md) (Growth Copilot).

| Status | Notes |
|--------|-------|
| **UNKNOWN** | No `AdsResource` in `src/modules/catalog/domain/integrations/tiktok/` |

Confirm official Ads API paths and scopes in Partner Center before implementing P2-1.
Do not use TikTok for Business API (`business-api.tiktok.com`) unless Partner Center
documents it as the Shop Ads surface — **UNVERIFIED** until cited.

---

## Error codes (response envelope)

All endpoints return:

```json
{
  "code": 0,
  "message": "Success",
  "data": { },
  "request_id": "..."
}
```

| Code | Exception | Retry? |
|------|-----------|--------|
| 0 | Success | — |
| 100002 | `AuthenticationError` | Refresh token / re-auth |
| 100003 | `PermissionDeniedError` | Re-consent / scope request |
| 100004 | `ResourceNotFoundError` | No |
| 100005 | `RateLimitError` | Yes — backoff |
| 100006 | `TikTokSystemError` | Yes — transient |

**Source:** `src/modules/catalog/domain/integrations/tiktok/exceptions.py`
