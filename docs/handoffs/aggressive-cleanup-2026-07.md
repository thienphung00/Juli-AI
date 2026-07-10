# Aggressive codebase cleanup handoff

**Date:** 2026-07-10  
**Scope:** Full-monorepo dead-code removal per cleanup plan (creators/recommendations preserved).

---

## Test baseline vs final

| Suite | Before | After | Delta |
|-------|--------|-------|-------|
| `pytest` | 516 passed, 1 failed (pre-existing) | 486 passed, 1 failed (same) | −30 tests removed with dead surfaces |
| `pnpm test` (web) | 563 passed | 549 passed | −14 tests removed with deleted pages |

Pre-existing failure (unchanged): `tests/unit/test_feature_store_docs.py::test_system_design_cross_links_inference_signatures`

Doc contract suite: **15 passed**

---

## Issues completed

| # | Change | Gate |
|---|--------|------|
| 1 | Removed `sync_inventory`, `sync_settlements`, `sync_livestreams`; `backfill_shop` → creators only; dropped `publish_fn` alias | `test_polling.py`, `test_webhook.py` |
| 2 | Removed API routers: inventory, settlements, livestreams, analytics, alerts; trimmed `test_api_*` files | API unit tests |
| 3 | Deleted `/inventory`, `/livestreams`, `/alerts` pages + components; removed 4 frontend test files; trimmed `api-client.ts` | `pnpm test` |
| 4 | Archived `docs/features/mvp_1.*` → `docs/handoffs/archive/features/`; fixed `map.md` + MODULE.md `src/` refs; deleted `scripts/archive/migrate_backend_252.py` | doc contract tests |
| 5 | Added `scripts/clean-local.sh`; documented in `infra/deploy/README.md` | script executable |

---

## Deferred (per plan)

| Item | Reason |
|------|--------|
| `debug_tiktok` + `test_tiktok_verify_connection.py` | App Review / P2-A1 verify-connection still active |
| TikTok OAuth path consolidation | In-flight credential isolation work on branch |
| `intelligence/scoring` module removal | User constraint — creators/recommendations surface preserved |
| Web test consolidation (issue-numbered files) | High regression risk; only removed tests tied to deleted surfaces |

---

## Preserved surfaces (explicit)

- `creators` + `recommendations` routers and engine
- `intelligence/scoring` + `forecasting` (recommendations dependencies)
- `orders` + `products` API routes (P2-A1)
- Polling: `sync_orders`, `sync_products`, `sync_creators`, `sync_returns`
- TikTok client resources (`InventoryResource`, etc.) — client code kept for sandbox contracts
- Phase 2.5 deploy pipeline, Alembic migrations, CI gates

---

## Operator note

Router surface changed on production API. After merge, redeploy `juli-api` on VPS if App Review smoke checklist references removed endpoints (`/v1/inventory`, `/v1/alerts`, etc.). Legacy web redirects (`legacy-redirects.js`) still route old URLs to Home/operation.

```bash
cd ~/Juli-AI-v2 && git pull
sudo cp infra/deploy/systemd/juli-api.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl restart juli-api
APP_DOMAIN=app-juli.com API_DOMAIN=api.app-juli.com ./infra/deploy/smoke-test.sh
```
