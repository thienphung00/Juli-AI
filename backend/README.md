# backend/

Python backend services for Juli AI.

| Module | Purpose | Legacy source |
|--------|---------|---------------|
| [`api/`](api/) | FastAPI REST API (`api.app-juli.com`) | `src/apps/api_gateway/` |
| [`workers/`](workers/) | Celery workers, cron polling | `src/apps/cron_jobs/` |
| [`ai/`](ai/) | ML inference, copy layer, feature engineering | `src/modules/ml/` |
| [`integrations/`](integrations/) | TikTok API client, webhooks, ETL | `src/modules/catalog/`, `src/modules/ordering/` |
| [`database/`](database/) | SQLAlchemy models, repos, Alembic migrations | `src/shared/utils/data/`, `alembic/` |

**Status:** Runtime code lives here; `src/` retains documented compatibility shims (issue #252).

**Not to be confused with `src/apps/`** — that is the legacy backend entrypoint path.

See [`docs/architecture/migration-plan.md`](../docs/architecture/migration-plan.md).
