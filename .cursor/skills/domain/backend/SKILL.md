---
name: backend-executor
description: >-
  Executor Agent domain skill for Juli product logic and /v1/* FastAPI API.
  Use when implementing scoring, copy, action cards, aggregates, auth, or
  product services — not vendor I/O or schema/ETL durability.
---

# Backend Executor

Juli product logic and `/v1/*` API. TDD + artifact handoff:
[`agent-runtime/docs/agent-runtime.md`](../../../agent-runtime/docs/agent-runtime.md).

## When to load

| Signal | Also load |
|--------|-----------|
| FastAPI route, service, dependency | `code-quality.mdc`, `python-patterns`, `patterns.mdc` |
| pytest / API tests | `python-testing` |
| User input, auth, PII | `security.mdc`, `reliability.mdc` |
| Celery / background jobs | `reliability.mdc`, `observability.mdc` |
| Vendor HTTP, webhooks, sync | **`integrations`** — not here |

## Owns / Does not own

**Owns:** `/v1/*` routes (`api/routes/`), Juli JWT/session auth (`core/security/`),
product services (scoring, copy, action cards, aggregates, execution, alerts,
feedback, operations), Celery workers for product orchestration.

**Does not own:** **`integrations`** (vendor I/O), **`data-platform`** (schema/repos/ETL),
**`machine-learning`** (`backend/src/juli_backend/ai/`), **`ui-ux`** (`apps/dashboard`, `apps/demo`).

## Required context + load map

- `MODULE.md` under `backend/src/juli_backend/`; [ADR-031](../../../docs/adr/031-integrations-executor-domain.md)
- **Standard + exemplars:** [`docs/architecture/code-standard.md`](../../../docs/architecture/code-standard.md)
  — copy `services/agent_runs/` for a service and `api/routes/agent_runs.py` for a route
- **Load map:** `SKILL.md` → `REFERENCE.md` → `domain/testing-patterns/python-{patterns,testing}.md`

## Juli recipes

**App factory** — `api/app.py:create_app()` mounts `/v1/*`; vendor webhooks outside `/v1` when required.

**Route** — thin `api/routes/` handler, in this order: resolve the tenant (404, never 403),
apply gates, call the service, map its typed exception to HTTP, commit, enqueue. Pydantic
`response_model`, bounded pagination. Exemplar: `api/routes/agent_runs.py`.

**Auth** — `core/security/dependencies.py:get_current_user`; override via
`app.dependency_overrides` in tests (`tests/unit/test_api.py`).

**Service** — behaviour in `services/<domain>/`; failures are typed exceptions carrying a
machine-readable `error_code`; the service never commits. Public API in `MODULE.md`; no vendor
HTTP. Exemplar: `services/agent_runs/confirmations.py`.

**Worker** — `workers/tasks/` + `workers/celery_app.py`; shop-scoped, idempotent.

Deeper patterns: [`REFERENCE.md`](REFERENCE.md).

## Domain test surfaces

- **API:** the `auth_client` / `tenant` / `shop` / `app` fixtures (`tests/unit/conftest.py`, built
  on `tests/support/api.py`); a second tenant via `tests.support.api.authenticated_client`
- **Service:** async tests on the SQLite `session`; rows from `tests/support/builders`;
  `asyncio_mode = auto`, so no `pytest.mark.asyncio`
- Doubles are hand-written with the real signatures (`tests/support/fakes.py`), never `MagicMock`
- Vertical RED→GREEN; assert status + envelope, not call order

TDD + artifact: see `agent-runtime/docs/agent-runtime.md` (surfaces above only).

## Implementation artifact

```bash
python agent-runtime/scripts/ci/generate_implementation_artifact.py --issue <n> --executor-domain backend
```

## Review focus

Auth/authz at service layer, API envelope (`patterns.mdc`), idempotency, safe logging.
Structure: `intent-review`.

## Validation

`pytest`, `ruff check backend/src/juli_backend tests scripts && ruff format --check`, `mypy backend/`;
schema changes → `data-platform`.

## Must not

Vendor HTTP/webhooks/analytics fetch; migrations/repos/ETL dedup; ship or validate.
