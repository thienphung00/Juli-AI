# Module: api

## Responsibility
FastAPI REST API with versioned routing (/v1/*), auth middleware integration,
and shop-scoped request context for the Juli platform.

## Public Interface
- `create_app() -> FastAPI` — builds the application with all routers wired
- `get_active_shop(x_shop_id, user, session) -> Shop` — FastAPI dependency resolving X-Shop-Id header to an owned Shop
- `GET /v1/shops` — list authenticated user's shops
- `GET /v1/shops/me` — get the shop identified by X-Shop-Id header
- `GET /v1/orders` — list orders with status/date/product filters, cursor pagination (#37)
- `POST /v1/orders/{id}/confirm-shipment` — mark order as shipped (#37)
- `GET /v1/products` — list products ranked by revenue with units sold (#37)
- `GET /v1/inventory` — list inventory with velocity indicator per SKU (#37)
- `GET /v1/analytics/revenue` — daily/weekly/monthly GMV with trend direction (#37)
- `GET /v1/livestreams` — paginated list of livestream sessions with duration, viewers, peak concurrent, orders (#38)
- `GET /v1/creators` — paginated list of creators with GMV attribution and commission efficiency (#38)
- `GET /v1/creators/{id}/content` — content-to-conversion funnel (views → clicks → orders) for a creator (#38)
- `GET /v1/settlements` — paginated list of settlements with net revenue after deductions (#38)
- `GET /v1/alerts/history` — paginated alert history for the active shop (#43)
- `PUT /v1/alerts/config` — create/update per-shop alert rules and thresholds (#43)
- `GET /v1/recommendations` — active recommendations with Vietnamese message + CTA (#43)
- `GET /v1/analytics/daily` — yesterday's profit breakdown by SKU and prep checklist (#43)

## Dependencies
- `auth` — `get_current_user` for JWT-based authentication
- `data` — repos and models for shop-scoped persistence
- `alerts` — `configure_rules` for threshold CRUD (#43)
- `recommendations` — engine functions for on-demand recommendation refresh (#43)
- `intelligence/forecasting` — `get_low_stock_risks` for prep checklist (#43)

## Invariants
- All /v1/* endpoints require a valid Supabase JWT (401 on failure)
- X-Shop-Id header is validated against user ownership (403 on mismatch)
- No endpoint leaks data across tenants — all queries scoped by authenticated user
- All list endpoints use cursor-based pagination with `limit` + `after` params
- Confirm-shipment only transitions from AWAITING_SHIPMENT → SHIPPED (409 otherwise)

## Owners
- domain: api
- code: src/api/
