# backend/

Python backend services for Juli AI.

| Module | Purpose |
|--------|---------|
| [`api/`](api/) | FastAPI REST API (`api.app-juli.com`) |
| [`workers/`](workers/) | Celery workers, cron polling |
| [`ai/`](ai/) | ML inference, copy layer, feature engineering |
| [`integrations/`](integrations/) | TikTok API client, webhooks, ETL |
| [`database/`](database/) | SQLAlchemy models, repos, Alembic migrations |

**Status:** Canonical Python runtime (Phase 2.5-c complete; `src/` shims removed pre-Phase 2).

**Not to be confused with top-level `apps/`** — product deployables live under `apps/`.

See [`docs/architecture/migration-plan.md`](../docs/architecture/migration-plan.md).
