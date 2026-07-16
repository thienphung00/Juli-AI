# Juli AI

Decision Copilot for TikTok Shop sellers — ingest shop data, surface signals,
collect explicit approval, and execute via tools.

## Repository layout

| Path | Purpose |
|------|---------|
| [`apps/dashboard/`](apps/dashboard/) | Next.js seller dashboard (`app-juli.com`) |
| [`backend/`](backend/) | Python FastAPI backend (`juli_backend` package) |
| [`ios/`](ios/) | Native iOS app |
| [`infra/`](infra/) | VPS deploy scripts, nginx, systemd |
| [`docs/`](docs/) | Architecture, ADRs, runbooks, product specs |
| [`agent-runtime/`](agent-runtime/) | Agent harness config, scripts, artifacts (ADR-003) |
| [`scripts/`](scripts/) | CI, validation, and harness scripts |

Start with [`EXECUTION.md`](EXECUTION.md) for phase scope and [`docs/README.md`](docs/README.md) for documentation routing.

## Local development

### Backend

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e "./backend[dev]"
cp .env.example .env   # fill in DATABASE_URL and other secrets
./infra/scripts/safe-alembic-upgrade-local.sh
uvicorn juli_backend.api.main:app --reload --host 127.0.0.1 --port 8000
```

See [`backend/README.md`](backend/README.md) for module map and deploy notes.

### Frontend

```bash
cd apps/dashboard
npm ci
npm run dev
```

Production build and CI gates: `npm run lint`, `npm run type-check`, `npm run test`, `npm run build`.

See [`apps/README.md`](apps/README.md).

## Tooling

- **Python:** `backend/pyproject.toml` (PEP 621 + Hatchling); root `requirements.txt` is generated for VPS deploy.
- **Node:** npm in `apps/dashboard/` (no pnpm/turbo workspace).
- **CI:** [`.github/workflows/pr.yml`](.github/workflows/pr.yml)
