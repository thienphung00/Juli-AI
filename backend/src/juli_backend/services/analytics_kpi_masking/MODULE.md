# backend/src/juli_backend/services/analytics_kpi_masking

## Purpose

Phase 2.10-A6 public Demo identity masking — pure transform over Analytics KPI
envelope payloads before unauthenticated GET responses (ADR-038 § Public Demo
masking). **Identity mask, real magnitudes**: alias shop display name and stable
demo aliases for merchant/order/SKU ids and product titles; preserve GMV/trend
numeric series unchanged. Buyer PII remains forbidden.

## Public API

- ``mask_public_analytics_envelope(envelope: dict) -> dict`` — deep-copy transform;
  aliases ``identity`` block fields; replaces top-level ``shop_id`` with stable
  demo alias; strips buyer PII keys; never alters KPI ``series`` numeric values.

## Payload contract (input)

Expects precompute envelope dict (see ``analytics_kpi_precompute/MODULE.md``) optionally
extended with an ``identity`` block:

```json
{
  "shop_id": "<uuid>",
  "identity": {
    "shop_display_name": "<real shop name>",
    "merchant_id": "<tiktok merchant id>",
    "products": [{"id": "...", "title": "...", "sku_id": "..."}],
    "orders": [{"id": "...", "product_title": "..."}]
  },
  "kpis": { "...": { "series": [{"t": "...", "v": <number>}] } }
}
```

## Masking rules

- Shop display name → ``Demo Shop {100-999}`` (stable per raw name)
- Product/order/SKU ids → ``demo-{kind}-{8-char hmac}`` (stable per raw id)
- Product titles → ``Demo Product {100-999}`` (stable per product id)
- ``merchant_id`` / ``tiktok_merchant_id`` removed from public payload
- Buyer PII keys (email, phone, address, …) stripped — not aliased
- **Never** apply numeric noise or scale-factor masking to KPI series

## Dependencies

- None (stdlib HMAC/SHA256 only). Consumed by public Demo read path (#531).

## Consumers

- ``GET /v1/demo/analytics`` (issue #531) — applies mask before HTTP response
