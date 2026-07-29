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
| FastAPI route, service, dependency | `python-patterns`, `patterns.mdc` |
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
- **Load map:** `SKILL.md` → `REFERENCE.md` → `domain/testing-patterns/python-{patterns,testing}.md`

## Juli recipes

**App factory** — `api/app.py:create_app()` mounts `/v1/*`; vendor webhooks outside `/v1` when required.

**Route** — thin `api/routes/` handler: Pydantic `response_model`, `Depends(get_current_user)`,
bounded pagination; delegate to repos/services.

**Auth** — `core/security/dependencies.py:get_current_user`; override via
`app.dependency_overrides` in tests (`tests/unit/test_api.py`).

**Service** — logic in `services/<domain>/`; public API in `MODULE.md`; no vendor HTTP.

**Worker** — `workers/tasks/` + `workers/celery_app.py`; shop-scoped, idempotent.

Deeper patterns: [`REFERENCE.md`](REFERENCE.md).

## Domain test surfaces

- **API:** `httpx.AsyncClient` + `ASGITransport(create_app())`; override `get_session` /
  `get_current_user`
- **Service:** async tests + SQLite `session` from `tests/unit/conftest.py`
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

`pytest`, `ruff check .`, `mypy backend/`; schema changes → `data-platform`.

## Must not

Vendor HTTP/webhooks/analytics fetch; migrations/repos/ETL dedup; ship or validate.
