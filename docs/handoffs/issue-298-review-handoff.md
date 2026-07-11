# Review handoff — Issue #298

> **Executor:** backend · **phaseRunId:** `2026-07-11T0031Z`  
> **Implementation artifact:** [`agent-runtime/artifacts/implementations/implementation-issue-298.json`](../../agent-runtime/artifacts/implementations/implementation-issue-298.json)

## Scope

P2-A1 Fujiwa polling orchestration: wire production-read scheduled polling for orders, products, returns with pagination (Layer 1 resources), rate-limit backoff, token refresh, and per-endpoint persisted sync state.

## Acceptance criteria → tests

| Criterion | Test |
|-----------|------|
| Fujiwa only — never SANDBOX_VN | `test_fujiwa_polling_orchestration.py::test_fujiwa_only_rejects_sandbox_credential` |
| Sync state persisted per endpoint | `test_save_and_load_per_endpoint`, `test_persists_sync_state_per_endpoint`, `test_resumes_from_persisted_sync_state` |
| Rate-limit backoff without worker crash | `test_completes_when_all_endpoints_rate_limited` |

## TDD evidence

- **RED→GREEN cycles 1–2:** sync state model/repo + orchestrator (9 tests)
- **REFACTOR cycle 3:** `_PollStep` data-driven loop, batched `TikTokSyncStateRepo.save`, `run_poll` test fixture — 26 tests still green

## Modules touched

- `backend/src/juli_backend/workers/services/polling/orchestrate.py` — `run_fujiwa_poll_cycle`, `FujiwaPollConfig`
- `backend/src/juli_backend/repositories/repos.py` — `TikTokSyncStateRepo`
- `backend/src/juli_backend/models/models.py` — `TikTokSyncState`
- `backend/src/juli_backend/integrations/tiktok/rate_limiter.py` — `is_exhausted()`
- `backend/src/juli_backend/database/migrations/versions/009_tiktok_sync_state.py`
- `tests/unit/test_fujiwa_polling_orchestration.py`

## Review focus

- Fujiwa credential guard cannot be bypassed via injectable `resolve_credential` in production wiring
- Migration 009 required before poll cycles persist state
- Rate-limit backoff sleeps in-process (long TTL extends cycle duration)
- Celery beat wiring deferred — `run_fujiwa_poll_cycle` is schedulable entry point only

## Suggested test command

```bash
cd backend && python -m pytest \
  ../tests/unit/test_fujiwa_polling_orchestration.py \
  ../tests/unit/test_polling.py \
  ../tests/unit/test_layer1_read_resources.py -q
```

## Blocked downstream

- **#299** ETL normalization (blocked by #298)
