# Backend reference (Juli product + /v1 API)

Curated patterns for the 80% path. For library API details and churn-prone behavior,
use the **Context7 CLI** at Executor time when Focus/Meta selects it (see **Sources /
live Context7 pointers**). Load on demand — not always injected in full.

---

## 1. App factory and `/v1` routing

- **Factory:** `juli_backend.api.app:create_app()` builds `FastAPI`, mounts `APIRouter(prefix="/v1")`,
  includes product routers (shops, orders, recommendations, action_cards, …).
- **Vendor webhooks:** routes that must match Partner Center literal paths stay outside `/v1`
  (see `webhook_tiktok_router` comment in `app.py`).
- **Startup:** `api/main.py` wires lifespan → `init_session_factory()` before serving.

---

## 2. Dependency injection and auth

- **Session:** `database.database:get_session` yields `AsyncSession` from process-wide factory.
- **Auth:** `core/security/dependencies.py:get_current_user` — Bearer JWT → `UsersRepo.get`.
- **Shop scope:** `api/dependencies.py:get_active_shop` — `X-Shop-Id` header + user ownership check.
- **Override in tests:** assign callables to `app.dependency_overrides[dep_fn]`; clear after test.

Context7 extract (`/websites/fastapi_tiangolo` — dependency overrides):

```python
app.dependency_overrides[get_settings] = get_settings_override
# ... run tests ...
app.dependency_overrides.clear()
```

Repo pattern (`tests/unit/test_api.py`):

```python
application.dependency_overrides[get_session] = _test_session
application.dependency_overrides[get_current_user] = lambda: authenticated_user
```

---

## 3. API testing with httpx ASGITransport

Context7 extract (`/encode/httpx` — ASGITransport):

```python
transport = httpx.ASGITransport(app=app)
async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
    r = await client.get("/v1/shops")
    assert r.status_code == 401
```

- Prefer **async** client + `pytest.mark.asyncio` (repo convention).
- Assert **status + envelope** (`detail`, list shape, pagination bounds) — not internal call order.
- SQLite in-memory engine from `tests/unit/conftest.py` for repo-backed routes.

---

## 4. Pydantic v2 response models

Context7 extract (`/pydantic/pydantic`):

```python
class ShopResponse(BaseModel):
    id: uuid.UUID
    shop_name: str
    model_config = {"from_attributes": True}  # ORM → response
```

- **`BaseSettings`** lives in `pydantic-settings`, not core `pydantic` (v2 migration).
- Route handlers return ORM objects when `response_model` uses `from_attributes=True`.
- Validate inbound bodies with explicit models; avoid raw `dict` at HTTP boundary.

---

## 5. Service layer conventions

- **Public surface:** functions/classes listed in each `services/*/MODULE.md`.
- **Scoring pipeline:** `services/scoring/` — rules-based batch; no vendor HTTP; reads repos only.
- **Action cards / aggregates / execution:** shop-scoped writes through repos; idempotent refresh paths.
- **Workers:** `workers/tasks/` dispatch Celery jobs; keep vendor I/O in `integrations` modules.

**Boundary:** product services must not import `integrations.tiktok.client` for new features —
accept data via repos or injected callables from integration handoff.

---

## 6. Juli path cheat-sheet

| Concern | Module(s) |
|---------|-------------|
| App factory + `/v1` routers | `api/app.py`, `api/routes/` |
| Auth + JWT | `core/security/` |
| Async session DI | `database/database.py` |
| Product services | `services/scoring/`, `action_cards/`, `aggregates/`, `execution/`, `alerts/` |
| Celery | `workers/celery_app.py`, `workers/tasks/` |
| ML code (defer to `machine-learning` domain) | `backend/src/juli_backend/ai/` |
| Frontend apps (defer to `ui-ux`) | `apps/dashboard`, `apps/demo` |
| Vendor I/O (defer to `integrations`) | `integrations/tiktok/`, `services/webhook/` |

---

## 7. Sources / live Context7 pointers

This workspace uses the **Context7 CLI** (`npx ctx7@latest`), not Context7 MCP.

```bash
npx ctx7@latest library fastapi "dependency_overrides testing"
npx ctx7@latest docs /websites/fastapi_tiangolo "dependency_overrides testing"
npx ctx7@latest docs /encode/httpx "ASGITransport AsyncClient"
npx ctx7@latest docs /pydantic/pydantic "model_validate from_attributes BaseSettings"
```

| Topic | Suggested CLI queries |
|-------|----------------------|
| Dependency overrides | `docs /websites/fastapi_tiangolo` — `app.dependency_overrides`, Annotated deps |
| Async test client | `docs /encode/httpx` — `ASGITransport`, `AsyncClient`, `base_url` |
| Response models | `docs /pydantic/pydantic` — `model_config`, `from_attributes`, settings package |
| Celery task contracts | `library celery` → `docs <id>` — retry, acks_late (when touching workers) |

**Example library IDs** (resolve with `library` before use): `/websites/fastapi_tiangolo`,
`/encode/httpx`, `/pydantic/pydantic`.

See [`.cursor/rules/context7-cli.mdc`](../../../rules/context7-cli.mdc).

**Repo authority:** `MODULE.md` for affected modules,
[ADR-031](../../../docs/adr/031-integrations-executor-domain.md),
[`patterns.mdc`](../../../rules/patterns.mdc).
