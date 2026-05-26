# Module: api

## Responsibility
FastAPI REST API with versioned routing (/v1/*), auth middleware integration,
and shop-scoped request context for the Juli platform.

## Public Interface
- `create_app() -> FastAPI` — builds the application with all routers wired
- `get_active_shop(x_shop_id, user, session) -> Shop` — FastAPI dependency resolving X-Shop-Id header to an owned Shop
- `GET /v1/shops` — list authenticated user's shops
- `GET /v1/shops/me` — get the shop identified by X-Shop-Id header

## Dependencies
- `auth` — `get_current_user` for JWT-based authentication
- `data` — `ShopsRepo`, `Shop`, `User`, `get_session` for persistence

## Invariants
- All /v1/* endpoints require a valid Supabase JWT (401 on failure)
- X-Shop-Id header is validated against user ownership (403 on mismatch)
- No endpoint leaks data across tenants — all queries scoped by authenticated user

## Owners
- domain: api
- code: src/api/
