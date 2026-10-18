# Juli AI

Decision Copilot for TikTok Shop sellers — ingest shop data, surface signals,
collect explicit approval, and execute via tools.

## Repository layout

| Path | Purpose |
|------|---------|
| [`apps/`](apps/) | Next.js apps: `landing` (`app-juli.com`), `demo` (`demo.app-juli.com`, `ops.app-juli.com`), plus the `connector` extension |
| [`packages/`](packages/) | Shared pnpm workspace packages (`ui`, `theme`, `contracts`, …) |
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
pnpm install
pnpm dev            # demo :3100 and landing :3007
```

Gates: `pnpm check:demo` and `pnpm check:landing` (lint, type-check, test, build).

See [`apps/README.md`](apps/README.md).

## Tooling

- **Python:** `backend/pyproject.toml` (PEP 621 + Hatchling); root `requirements.txt` is generated for VPS deploy.
- **Node:** pnpm workspace + turbo (`pnpm-workspace.yaml`, `turbo.json`). The old npm-owned `apps/dashboard` was deleted in fast-track P53 (C1).
- **CI:** [`.github/workflows/pr.yml`](.github/workflows/pr.yml)
