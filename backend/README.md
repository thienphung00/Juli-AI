# backend/

Python backend services for Juli AI (`juli_backend` package, PEP 621 src layout).

| Module | Purpose |
|--------|---------|
| [`src/juli_backend/api/`](src/juli_backend/api/) | FastAPI REST API (`api.app-juli.com`) |
| [`src/juli_backend/workers/`](src/juli_backend/workers/) | Celery workers, cron polling |
| [`src/juli_backend/ai/`](src/juli_backend/ai/) | ML inference, copy layer, feature engineering |
| [`src/juli_backend/integrations/`](src/juli_backend/integrations/) | TikTok API client, webhooks, ETL |
| [`src/juli_backend/database/`](src/juli_backend/database/) | SQLAlchemy models, repos, Alembic migrations |

## Local setup

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e "./backend[dev]"
cp .env.example .env   # fill in DATABASE_URL and other secrets
alembic upgrade head
uvicorn juli_backend.api.api.main:app --reload --host 127.0.0.1 --port 8000
```

The backend loads repo-root `.env` automatically for local dev (via `python-dotenv` in
`runtime.py`). You do not need to `source .env` before `alembic` or `uvicorn`.

`requirements.txt` at the repo root is generated from `backend/pyproject.toml` for
VPS deploy scripts that install runtime deps before `pip install -e ./backend`.

**Not to be confused with top-level `apps/`** — product deployables live under `apps/`.

See [`docs/architecture/migration-plan.md`](../docs/architecture/migration-plan.md).
