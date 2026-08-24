# Module: api

## Responsibility
FastAPI REST API with versioned routing (/v1/*), auth middleware integration,
and shop-scoped request context. Phase 1 (Creator ↔ Shop Matching) surface only —
decision-focused, not dashboard/reporting.

## Public Interface

No package-root ``__all__`` yet. Deploy and tests import entry points from submodules:

```python
from juli_backend.api.app import create_app
from juli_backend.api.dependencies import get_active_shop
```

- `create_app(*, lifespan=None) -> FastAPI` — builds the application with routers wired
  (`juli_backend.api.app`)
- `get_active_shop(x_shop_id, user, session) -> Shop` — FastAPI dependency resolving
  X-Shop-Id header to an owned Shop (`juli_backend.api.dependencies`)

### HTTP surface

- `GET /v1/shops` — list authenticated user's shops
- `GET /v1/shops/me` — get the shop identified by X-Shop-Id header
- `GET /v1/creators` — creators with attribution + commission efficiency (matching signal)
- `GET /v1/creators/{id}/content` — content-to-conversion funnel for a creator
- `GET /v1/products` — products (product nodes for matching)
- `GET /v1/orders` — shop-scoped orders
- `GET /v1/recommendations` — decision-focused recommendations: match/justification + CTA;
  empty shop triggers legacy persist via `services/action_cards.persist_legacy_recommendations`
  (read-only route — no direct `RecommendationsRepo.create`)
- `GET /v1/demo/analytics` — unauthenticated masked Analytics envelope for the
  server-configured reference shop (Issue #531, ADR-037). No visitor `shop_id`;
  read-through Redis → Postgres SoT; masking applied before response.
- `POST /v1/demo/decisions/{action_card_id}/approve` — authenticated
  approve-is-run-creation (ADR-075 decision 1, ADR-082, #1222).
  `get_current_user` + `get_active_shop`, shop scope from the caller's
  `X-Shop-Id` header. Originally (#717, B-5, ADR-037/038 §9) this route was
  unauthenticated, server-configured-reference-shop-bound, and created a
  local `DemoExecutionRecord` dry-run only; #1222 retired that behaviour
  and made this the sole way a real `workflow_runs` row comes into
  existence. See `api/routes/demo_execution.py`'s own docstring and
  `services/demo_execution/MODULE.md`'s "Retired call site" section for
  the full history (that module is left in place, registered but
  unreachable from HTTP, rather than deleted).
- `GET /v1/demo/decisions` / `GET /v1/demo/decisions/{action_card_id}` —
  authenticated Demo Decisions read (originally #718, B-6, ADR-037/038; auth
  posture updated by #1283, AGT-W5A, ADR-075 decision 3). `get_current_user`
  + `get_active_shop`, same as every other authenticated route — shop scope
  resolves from the caller's `X-Shop-Id` header, never a server-bound
  reference shop. Returns the ranked, emission-gated
  (`ActionCard.surfaced_at`-gated) active Decision set for the caller's own
  shop only — a suppressed candidate, or a card belonging to any other shop,
  404s identically to a nonexistent id on detail lookup; a shop with zero
  cards gets an empty list, never another shop's. See
  `services/demo_decisions/MODULE.md`.
- `POST /webhooks/tiktok` — TikTok Shop webhook ingress (Issue #381), not under `/v1`.
  Mounted from `juli_backend.services.webhook`; see `api/routes/webhook_tiktok.py` and
  `services/webhook/MODULE.md`.

## Removed in the matching pivot
`orders`, `inventory`, `settlements`, `analytics`, `livestreams`, and `alerts`
routers were deleted as misaligned with Phase 1 (inventory/finance/order management,
analytics, and threshold alerting). See `docs/adr/006-matching-pivot.md`.

## Dependencies
- `core/security` — `get_current_user` for JWT-based authentication
- `database` — repos and models for shop-scoped persistence
- `services/action_cards` — legacy recommendation persist delegate (MMU-11); scoring refresh enqueue
- `services/demo_execution` — Demo approve → dry-run execute (#717, B-5); reads
  `ActionCard` directly, never imports `services/execution` or `integrations/tiktok`
- `services/demo_decisions` — Demo Decisions read (#718, B-6); reads
  `ActionCard` directly, read-only, allowlist-masks the response for the
  authenticated caller's own shop (#1283)
- `ai/recommendations` — engine functions consumed by action_cards owner (not API writes)

## Invariants
- All /v1/* endpoints require a valid Supabase JWT (401 on failure), except
  `GET /v1/demo/analytics`, which is intentionally public (ADR-037).
  `GET /v1/demo/decisions`, `GET /v1/demo/decisions/{id}`, and
  `POST /v1/demo/decisions/{id}/approve` are all authenticated
  (`get_current_user` + `get_active_shop`) — the last of the three demo
  routes to fall under this rule was `GET /v1/demo/decisions` /
  `GET /v1/demo/decisions/{id}` (#1283, ADR-075 decision 3; approve was
  already authenticated as of #1222)
- X-Shop-Id header is validated against user ownership (403 on mismatch)
- No endpoint leaks data across tenants — all queries scoped by authenticated user
- All list endpoints use cursor-based pagination with `limit` + `after` params

## Owners
- domain: api
- code: backend/src/juli_backend/api/
