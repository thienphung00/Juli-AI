# Pre-Phase 2 cleanup handoff

**Date:** 2026-07-04  
**Scope:** Close Phase 2.5, remove `src/` shims, align docs/CI, prepare Phase 2 Pipeline Validation.

---

## Structural changes completed

| Issue | Change | Gate |
|-------|--------|------|
| 1 | Canonical docs: `EXECUTION.md` active phase → Phase 2; Phase 2.5 exit gates checked; `migration-plan`, app_review, TikTok API paths, READMEs updated | Doc contract tests green |
| 2 | Deploy entrypoint: `juli-api.service` → `backend.api.api.main:app`; runbooks/nginx comments updated | Backend deploy + migration contract tests |
| 3 | Deleted `src/` shim tree; archived `scripts/migrate_backend_252.py`; updated `backend/` MODULE.md paths | Full `pytest` (506 tests) |
| 4 | `release.yml` mypy → `backend/`; `check_module_boundaries.py` + `common.py` scan `backend/`; removed empty scaffold dirs | Full `pytest` |
| 5 | This handoff + [ADR 019](../decisions/019-src-shim-removal.md); historical handoffs archived | — |

---

## Live deploy (unchanged behavior, new entrypoint)

App Review remains live at `app-juli.com` + `api.app-juli.com` (sign-off 2026-07-03).

**Operator HITL after merge** — redeploy backend entrypoint on VPS:

```bash
cd ~/Juli-AI-v2 && git pull
sudo cp infra/systemd/juli-api.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl restart juli-api
APP_DOMAIN=app-juli.com API_DOMAIN=api.app-juli.com ./infra/scripts/smoke-test.sh
```

Do **not** pull shim-deletion commits until the systemd unit above is installed, or
`juli-api` will fail to start.

---

## Phase status

### Phase 2.5 — complete

- App Review smoke: 11/11 passed (2026-07-03)
- OAuth callback + credential persistence in Postgres
- Reviewer login (UI-only demo)
- Backend runtime: `backend/` only (no `src/` shims)

### Phase 2 — active (Pipeline Validation)

**Next slice: P2-A1** — Contract-first TikTok read sync, SPS discovery, production read-only guards (see [`docs/tiktok_api/contract-collection.md`](../tiktok_api/contract-collection.md))

| Already done (pre-A1) | Still pending |
|----------------------|---------------|
| OAuth exchange + encrypted `TikTokCredential` persistence | Scheduled polling workers (`sync_orders`, `sync_products`, `sync_creators`) |
| `/debug/tiktok/verify-connection` (env-gated) | ETL → business entities (P2-A2) |
| Alembic identity tables on review VPS | Feature aggregates (P2-A3) |
| | Rules pipeline + Celery execution (Milestone B) |

**Key modules for P2-A1:**

- `backend/workers/services/polling/`
- `backend/integrations/catalog/domain/integrations/tiktok/`
- `backend/database/repos.py` (`TikTokCredentialRepo`)

**Note:** Polling workers were explicitly out of the App Review deploy envelope (ADR 017).
Phase 2 requires enabling them in a separate scheduler/worker deploy — not the review
`juli-api` single-process unit.

---

## Archived handoffs

Pre-Phase 2.5 issue handoffs (`issue-118-*` … `issue-199-*`, parallel trackers) moved to
[`archive/`](archive/) — historical only; do not use as active implementation guides.

---

## Test baseline

```bash
python -m pytest -q   # 506 passed (2026-07-04)
```

Phase 2.5 deploy contract suite:

```bash
python -m pytest tests/unit/test_phase_2_5_deploy_config.py \
  tests/unit/test_phase_2_5_frontend_deploy.py \
  tests/unit/test_phase_2_5_backend_deploy.py \
  tests/unit/test_phase_2_5_reviewer_login.py \
  tests/unit/test_phase_2_5_smoke_checklist.py \
  tests/unit/test_phase_2_5_backend_migration.py -q
```
