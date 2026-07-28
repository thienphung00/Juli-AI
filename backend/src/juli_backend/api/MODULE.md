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
- `GET /v1/recommendations` — decision-focused recommendations: match/justification + CTA;
  empty shop triggers legacy persist via `services/action_cards.persist_legacy_recommendations`
  (read-only route — no direct `RecommendationsRepo.create`)
- `GET /v1/demo/analytics` — unauthenticated masked Analytics envelope for the
  server-configured reference shop (Issue #531, ADR-037). No visitor `shop_id`;
  read-through Redis → Postgres SoT; masking applied before response.
- `POST /webhooks/tiktok` — TikTok Shop webhook ingress (Issue #381), not under `/v1`.
  Mounted from `juli_backend.services.webhook.app.build_webhook_service`; see
  `api/routes/webhook_tiktok.py` and `services/webhook/MODULE.md`.

## Removed in the matching pivot
`orders`, `inventory`, `settlements`, `analytics`, `livestreams`, and `alerts`
routers were deleted as misaligned with Phase 1 (inventory/finance/order management,
analytics, and threshold alerting). See `docs/adr/006-matching-pivot.md`.

## Dependencies
- `core/security` — `get_current_user` for JWT-based authentication
- `database` — repos and models for shop-scoped persistence
- `services/action_cards` — legacy recommendation persist delegate (MMU-11); scoring refresh enqueue
- `ai/recommendations` — engine functions consumed by action_cards owner (not API writes)

## Invariants
- All /v1/* endpoints require a valid Supabase JWT (401 on failure), except
  `GET /v1/demo/analytics` which is intentionally public (ADR-037)
- X-Shop-Id header is validated against user ownership (403 on mismatch)
- No endpoint leaks data across tenants — all queries scoped by authenticated user
- All list endpoints use cursor-based pagination with `limit` + `after` params

## Owners
- domain: api
- code: backend/src/juli_backend/api/
