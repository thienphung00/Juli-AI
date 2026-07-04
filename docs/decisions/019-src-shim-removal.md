# ADR 019: Remove `src/` compatibility shims after deploy entrypoint switch

**Status:** Accepted  
**Date:** 2026-07-04  
**Context:** Phase 2.5-c (#252) moved Python runtime to `backend/` and left thin `src/`
re-export shims so the live App Review VPS could keep using
`uvicorn src.apps.api_gateway.api.main:app` until deploy config was updated.

## Decision

After switching the systemd entrypoint to `backend.api.api.main:app` and verifying
smoke tests, **delete the entire `src/` Python shim tree** and treat `backend/` as the
only Python runtime location.

## Rationale

- All Python imports and tests already use `backend.*` (zero `src.*` imports in code).
- Maintaining duplicate shim paths increases doc drift and confuses new contributors.
- ADR 018 explicitly scoped shims as temporary until deploy entrypoint migration.

## Consequences

- **Positive:** Single runtime root; CI (`mypy`, module boundary checks) targets `backend/` only.
- **Positive:** Canonical docs and TikTok API architecture diagrams align with as-built layout.
- **Negative:** Operators must redeploy `juli-api` with the new systemd unit before pulling
  a commit that deletes `src/` (HITL step documented in handoff).
- **Migration script:** `scripts/migrate_backend_252.py` archived under `scripts/archive/`.

## Related

- [ADR 017](017-product-monorepo-deployment-architecture.md) — monorepo layout
- [ADR 018](018-backend-runtime-migration.md) — initial `backend/` migration
- [`docs/handoffs/pre-phase-2-cleanup.md`](../handoffs/pre-phase-2-cleanup.md)
