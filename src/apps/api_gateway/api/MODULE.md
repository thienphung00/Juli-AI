# Module: api

## Responsibility
FastAPI REST API with versioned routing (/v1/*), auth middleware integration,
and shop-scoped request context. Phase 1 (Creator ↔ Shop Matching) surface only —
decision-focused, not dashboard/reporting.

## Public Interface
- `create_app() -> FastAPI` — builds the application with the Phase-1 routers wired
- `get_active_shop(x_shop_id, user, session) -> Shop` — FastAPI dependency resolving X-Shop-Id header to an owned Shop
- `GET /v1/shops` — list authenticated user's shops
- `GET /v1/shops/me` — get the shop identified by X-Shop-Id header
- `GET /v1/creators` — creators with attribution + commission efficiency (matching signal)
- `GET /v1/creators/{id}/content` — content-to-conversion funnel for a creator
- `GET /v1/products` — products (product nodes for matching)
- `GET /v1/recommendations` — decision-focused recommendations: match/justification + CTA

## Removed in the matching pivot
`orders`, `inventory`, `settlements`, `analytics`, `livestreams`, and `alerts`
routers were deleted as misaligned with Phase 1 (inventory/finance/order management,
analytics, and threshold alerting) during the superseded creator-matching pivot.

## Dependencies
- `identity` — `get_current_user` for JWT-based authentication
- `shared/utils/data` — repos and models for shop-scoped persistence
- `catalog/domain/recommendations` — engine functions for recommendation refresh

## Invariants
- All /v1/* endpoints require a valid Supabase JWT (401 on failure)
- X-Shop-Id header is validated against user ownership (403 on mismatch)
- No endpoint leaks data across tenants — all queries scoped by authenticated user
- All list endpoints use cursor-based pagination with `limit` + `after` params

## Owners
- domain: api
- code: src/apps/api_gateway/api/
