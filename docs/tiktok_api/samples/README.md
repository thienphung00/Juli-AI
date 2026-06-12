# TikTok Shop API — Response Sample Capture

Committed JSON fixtures ground field-level verification for the Partner API client,
ETL mapping, and Revenue Leakage features. **Synthetic parquet under
`backtest/revenue_leakage/` is not a substitute** — it does not reflect live response
shapes from TikTok.

## Prerequisites

1. ISV app registered in [Partner Center](https://partner.tiktokshop.com) with scopes
   for the target resource (Orders, Products, Return/Refund, etc.).
2. OAuth completed for a **test shop** in the target region (VN recommended for Juli).
3. `shop_cipher` obtained from `GET /authorization/202309/shops` (or seller equivalent).

## Capture workflow (API Testing Tool)

1. Open Partner Center → **Documents** → **API Testing Tool**.
2. Select the **versioned** endpoint (e.g. `POST /order/202309/orders/search`), not
   legacy `/api/*` aliases.
3. Set query params: `app_key`, `timestamp`, `shop_cipher`, `sign` (tool may auto-sign).
4. Set header: `x-tts-access-token: <access_token>`.
5. Run with minimal filters (small `page_size`, narrow time window).
6. **Download or copy** the full HTTP response envelope `{ code, message, data, request_id }`.
7. Redact tokens, shop_cipher, and buyer PII before committing.

## File naming convention

```
docs/tiktok_api/samples/
  README.md                          # this file
  orders-search-response.json        # POST /order/202309/orders/search
  orders-detail-response.json        # GET  /order/202309/orders?ids=...
  products-search-response.json      # POST /product/202502/products/search
  returns-search-response.json       # POST /return_refund/202309/returns/search
  cancellations-search-response.json # POST /return_refund/202309/cancellations/search
```

Each file should include:

```json
{
  "_meta": {
    "captured_at": "2026-06-09",
    "region": "VN",
    "endpoint": "POST /order/202309/orders/search",
    "api_version": "202309",
    "shop_cipher_redacted": true
  },
  "response": {
    "code": 0,
    "message": "Success",
    "data": { }
  }
}
```

## CLI alternative (curl)

When the Testing Tool is unavailable, replay the signed request the client would send:

```bash
# Export credentials from your OAuth flow (never commit these)
export TTS_APP_KEY=...
export TTS_APP_SECRET=...
export TTS_ACCESS_TOKEN=...
export TTS_SHOP_CIPHER=...

# Use the deployed signing helper or Partner Center "Copy as cURL"
python -m scripts.tiktok_capture_sample orders-search  # future helper; manual curl OK
```

Store output under `docs/tiktok_api/samples/` using the naming convention above.

## Using samples in tests

1. Add a unit test that loads the fixture and asserts `normalize_order` / resource
   parsers extract expected fields.
2. Reference the fixture path in `integration-audit-2026-06.md` evidence tables.
3. When TikTok changes an API version, capture a new file rather than overwriting —
   suffix with version: `orders-search-202309-response.json`.

## Minimum set for P2 unblock

| Priority | Fixture | Unblocks |
|----------|---------|----------|
| P0 | `orders-search-response.json` | Orders migration, pagination, ETL mapping |
| P0 | `returns-search-response.json` | ReturnRefund resource, Revenue Leakage |
| P1 | `products-search-response.json` | Product version migration |
| P2 | `cancellations-search-response.json` | Buyer-cancel cluster |

## Security

- Never commit `access_token`, `refresh_token`, `app_secret`, or raw `shop_cipher`.
- Mask `user_id` / buyer identifiers in committed samples.
- Add `docs/tiktok_api/samples/*-live.json` to `.gitignore` if using local uncensored copies.
